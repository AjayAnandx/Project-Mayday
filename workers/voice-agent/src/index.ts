import { Agent, routeAgentRequest } from "agents";
import { withVoice } from "@cloudflare/voice";

// Ai and DurableObjectNamespace are global ambient types provided by
// @cloudflare/workers-types — no import needed.

export interface Env {
  AI: Ai;
  MyAgent: DurableObjectNamespace;
  MAYDAY_TURN_URL: string;
  MAYDAY_SYNC_URL: string;
  MAYDAY_TOKEN: string;
  DEEPGRAM_API_KEY: string;
}

// withVoice(Agent) adds the full voice pipeline (STT -> onTurn -> TTS).
const VoiceAgent = withVoice(Agent);

/**
 * Deepgram streaming speech-to-text transcriber.
 *
 * Opens a Deepgram listen WebSocket (via the Workers fetch+upgrade pattern so
 * we can send the Authorization header) and feeds raw linear16 PCM chunks.
 * Fires onUtterance on speech_final, onInterim for partials, onSpeechStart on
 * the VAD SpeechStarted event — matching the withVoice session contract.
 */
class DeepgramSTT {
  #key: string;
  #sampleRate: number;
  constructor(key: string, opts: { sampleRate?: number } = {}) {
    this.#key = key;
    this.#sampleRate = opts.sampleRate ?? 16000;
  }
  createSession(options: any) {
    return new DeepgramSTTSession(this.#key, this.#sampleRate, options);
  }
}

class DeepgramSTTSession {
  #ws: any = null;
  #connected = false;
  #closed = false;
  #pending: ArrayBuffer[] = [];
  #finalizedSegments: string[] = [];
  #onInterim?: (t: string) => void;
  #onUtterance?: (t: string) => void;
  #onSpeechStart?: () => void;

  constructor(key: string, sampleRate: number, options: any) {
    this.#onInterim = options?.onInterim;
    this.#onUtterance = options?.onUtterance;
    this.#onSpeechStart = options?.onSpeechStart;
    this.#connect(key, sampleRate);
  }

  async #connect(key: string, sampleRate: number) {
    try {
      const params = new URLSearchParams({
        encoding: "linear16",
        sample_rate: String(sampleRate),
        channels: "1",
        punctuate: "true",
        interim_results: "true",
        endpointing: "300",
        vad_events: "true",
        smart_format: "true",
      });
      const url = `https://api.deepgram.com/v1/listen?${params.toString()}`;
      const resp: any = await fetch(url, {
        headers: { Authorization: `Token ${key}` },
        upgrade: "websocket",
      } as any);
      const ws = resp.webSocket;
      if (!ws) {
        console.error("[DeepgramSTT] no websocket in response");
        return;
      }
      ws.accept();
      this.#ws = ws;
      this.#connected = true;
      ws.addEventListener("message", (ev: any) => this.#handle(ev));
      ws.addEventListener("close", () => {
        this.#connected = false;
      });
      ws.addEventListener("error", (ev: any) => {
        console.error("[DeepgramSTT] ws error", ev);
        this.#connected = false;
      });
      for (const c of this.#pending) ws.send(c);
      this.#pending = [];
    } catch (e) {
      console.error("[DeepgramSTT] connect error", e);
    }
  }

  feed(chunk: ArrayBuffer) {
    if (this.#closed) return;
    if (this.#connected && this.#ws) this.#ws.send(chunk);
    else this.#pending.push(chunk);
  }

  close() {
    if (this.#closed) return;
    this.#closed = true;
    this.#pending = [];
    if (this.#ws) {
      try {
        this.#ws.close();
      } catch {}
      this.#ws = null;
    }
    this.#connected = false;
  }

  #handle(ev: any) {
    if (this.#closed) return;
    const data = typeof ev.data === "string" ? JSON.parse(ev.data) : null;
    if (!data) return;
    if (data.type === "SpeechStarted") {
      this.#onSpeechStart?.();
      return;
    }
    if (data.type === "Results") {
      const transcript = data.channel?.alternatives?.[0]?.transcript ?? "";
      if (data.speech_final) {
        if (transcript) this.#finalizedSegments.push(transcript);
        const full = this.#finalizedSegments.join(" ").trim();
        this.#finalizedSegments = [];
        if (full) this.#onUtterance?.(full);
      } else if (data.is_final && transcript) {
        this.#finalizedSegments.push(transcript);
      } else if (!data.is_final && transcript) {
        const display = this.#finalizedSegments.length
          ? this.#finalizedSegments.join(" ") + " " + transcript
          : transcript;
        this.#onInterim?.(display);
      }
    }
  }
}

/**
 * Deepgram text-to-speech synthesizer.
 *
 * Streams synthesis from Deepgram's speak WebSocket and returns the full mp3
 * as an ArrayBuffer (the client is told audio_format = mp3). The withVoice
 * framework sends the returned buffer straight to the client.
 */
class DeepgramTTS {
  #key: string;
  constructor(key: string) {
    this.#key = key;
  }
  async synthesize(text: string, signal?: AbortSignal): Promise<ArrayBuffer> {
    const params = new URLSearchParams({ encoding: "mp3", sample_rate: "24000" });
    const url = `https://api.deepgram.com/v1/speak?${params.toString()}`;
    const resp: any = await fetch(url, {
      headers: {
        Authorization: `Token ${this.#key}`,
        "Content-Type": "application/json",
      },
      upgrade: "websocket",
    } as any);
    const ws = resp.webSocket;
    if (!ws) throw new Error("Deepgram TTS: no websocket in response");
    ws.accept();
    const chunks: Uint8Array[] = [];
    let resolveDone: () => void = () => {};
    const done = new Promise<void>((r) => (resolveDone = r));
    const finish = () => resolveDone();
    ws.addEventListener("message", (ev: any) => {
      if (typeof ev.data === "string") {
        try {
          const d = JSON.parse(ev.data);
          if (d.type === "close") finish();
        } catch {}
      } else if (ev.data instanceof ArrayBuffer) {
        chunks.push(new Uint8Array(ev.data));
      } else if (ev.data instanceof Uint8Array) {
        chunks.push(ev.data);
      }
    });
    ws.addEventListener("close", finish);
    ws.addEventListener("error", finish);
    if (signal?.aborted) {
      ws.close();
      throw new Error("aborted");
    }
    ws.send(JSON.stringify({ type: "Speak", text }));
    await done;
    try {
      ws.close();
    } catch {}
    let total = 0;
    for (const c of chunks) total += c.length;
    const out = new Uint8Array(total);
    let off = 0;
    for (const c of chunks) {
      out.set(c, off);
      off += c.length;
    }
    return out.buffer;
  }
}

export class MyAgent extends VoiceAgent<Env> {
  // Deepgram streaming STT (replaces Workers AI, which is quota-blocked).
  transcriber = new DeepgramSTT(this.env.DEEPGRAM_API_KEY);

  constructor(...args: any[]) {
    // @ts-ignore agents mixin forwards constructor args
    super(...(args as any));
    // Normalize any binary audio type the agents framework might deliver
    // (Uint8Array / ArrayBuffer[] / Blob) into a single ArrayBuffer so the
    // voice pipeline always receives what it expects.
    const innerOnMessage = (this.onMessage as any).bind(this);
    (this as any).onMessage = (connection: any, message: any) => {
      if (message instanceof Uint8Array) {
        message = message.buffer.slice(
          message.byteOffset,
          message.byteOffset + message.byteLength
        );
      } else if (Array.isArray(message)) {
        let total = 0;
        for (const b of message as ArrayBuffer[]) total += b.byteLength;
        const out = new Uint8Array(total);
        let off = 0;
        for (const b of message as ArrayBuffer[]) {
          out.set(new Uint8Array(b), off);
          off += b.byteLength;
        }
        message = out.buffer;
      } else if (typeof Blob !== "undefined" && message instanceof Blob) {
        message.arrayBuffer().then((ab: ArrayBuffer) => innerOnMessage(connection, ab));
        return;
      }
      return innerOnMessage(connection, message);
    };
  }

  // Deepgram streaming TTS (mp3 output to match client audio_format).
  tts = new DeepgramTTS(this.env.DEEPGRAM_API_KEY);

  // Drop only empty/whitespace transcripts before they reach the brain.
  afterTranscribe(transcript: string): string | null {
    const t = transcript.trim();
    return t.length === 0 ? null : t;
  }

  // Strip markdown so TTS doesn't read "**bold**" or "[links](url)" aloud.
  beforeSynthesize(text: string): string {
    return stripMarkdown(text);
  }

  // Called when the user finishes an utterance. Returns a text stream that is
  // fed straight into TTS.
  async onTurn(
    transcript: string,
    context: any
  ): Promise<string | AsyncIterable<string>> {
    // --- Primary path: the laptop brain (Mayday backend via tunnel) ---
    try {
      const res = await fetch(
        `${this.env.MAYDAY_TURN_URL}?token=${this.env.MAYDAY_TOKEN}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            transcript,
            history: context.messages ?? [],
          }),
          // Aborts automatically if the user interrupts mid-response.
          signal: context.signal,
        }
      );
      if (!res.ok || !res.body) throw new Error("brain unreachable");
      // Mayday streams plain text chunks (not SSE-framed); pipe to TTS.
      return streamBodyAsText(res.body);
    } catch {
      // --- Fallback: lightweight cloud LLM when the laptop is offline ---
      const out: any = await this.env.AI.run("@cf/meta/llama-3.2-3b-instruct", {
        messages: [
          {
            role: "system",
            content:
              "You are Mayday's lightweight voice mode. The user's laptop " +
              "assistant is offline, so answer casually without tools or memory.",
          },
          ...(context.messages ?? []),
        ],
      });
      const text: string =
        out?.response ?? "I'm here, but my laptop brain is offline right now.";
      return text;
    }
  }

  // Persist the conversation to Mayday when the call ends (best-effort).
  async onCallEnd(connection: any): Promise<void> {
    const messages = connection?.ctx?.messages ?? [];
    if (!messages.length) return;
    fetch(`${this.env.MAYDAY_SYNC_URL}?token=${this.env.MAYDAY_TOKEN}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages }),
    }).catch(() => {});
  }
}

// Convert a binary ReadableStream (Mayday's text chunks) into an async
// iterable of strings for TTS.
async function* streamBodyAsText(
  body: ReadableStream<Uint8Array>
): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) yield decoder.decode(value, { stream: true });
  }
}

// Port of Mayday's backend/_make_voice_text markdown stripping.
function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/~~([^~]+)~~/g, "$1")
    .replace(/^>\s+/gm, "")
    .replace(/^[*-]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/<[^>]*>/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// Module Worker entry: route agent requests (incl. the voice WebSocket at
// /agents/my-agent/default) through the agents framework. `routeAgentRequest`
// maps the `my-agent` party to the `MyAgent` Durable Object binding and lets
// the Agent's Server base handle the WebSocket upgrade.
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return new Response("OK", { status: 200 });
    }
    return (await routeAgentRequest(request, env)) ?? new Response("Not found", { status: 404 });
  },
};
