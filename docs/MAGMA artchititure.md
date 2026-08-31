# MAGMA: A Multi-Graph based Agentic Memory Architecture for AI Agents

Dongming Jiangα, Yi Liα, Guanpeng Liβ and Bingzhe Liα

αUniversity of Texas at Dallas βUniversity of Florida

{dongming.jiang, yi.li3, bingzhe.li}@utdallas.edu; liguanpeng@ufl.edu

## Abstract

Memory-Augmented Generation (MAG) ex- tends Large Language Models with external memory to support long-context reasoning, but existing approaches largely rely on semantic similarity over monolithic memory stores, en- tangling temporal, causal, and entity informa- tion. This design limits interpretability and alignment between query intent and retrieved evidence, leading to suboptimal reasoning ac- curacy. In this paper, we propose MAGMA, a multi-graph agentic memory architecture that represents each memory item across orthogonal semantic, temporal, causal, and entity graphs. MAGMA formulates retrieval as policy-guided traversal over these relational views, enabling query-adaptive selection and structured context construction. By decoupling memory represen- tation from retrieval logic, MAGMA provides transparent reasoning paths and fine-grained control over retrieval. Experiments on Lo- CoMo and LongMemEval demonstrate that MAGMA consistently outperforms state-of-the- art agentic memory systems in long-horizon reasoning tasks.

Moreover, LLMs lack native mechanisms for stable and structured memory, resulting in inconsistent re- call, degraded long-horizon reasoning, and limited support for tasks requiring persistent and organized memory (Khandelwal et al., 2018; Maharana et al., 2024). [URL 🔗](#page-0)

To address these inherent limitations, Memory- Augmented Generation (MAG) systems have emerged as a promising direction for enabling LLMs to operate beyond the boundaries of their fixed context windows. MAG equips an agent with an external memory continuously recording inter- action histories and allowing the agents to retrieve and reintegrate past experiences when generating new responses. By offloading long-term context to an explicit memory module, MAG systems provide a means for agents to accumulate knowledge over time, support multi-session coherence, and adapt to evolving conversational or task contexts. In this paradigm, memory is no longer implicit in inter- nal activations but becomes a persistent, queryable resource that substantially enhances long-horizon reasoning, personalized behavior, and stable agent identity.

## 1 Introduction

Large Language Models (LLMs) have demon- strated remarkable capabilities across a wide range of tasks (Brown et al., 2020; Achiam et al., 2023; Wei et al., 2022), yet they remain limited in their ability to maintain and reason over long-term con- text. These models process information within a finite attention window, and their internal represen- tations do not persist across interactions, causing earlier details to be forgotten once they fall out- side the active context (Brown et al., 2020; Belt- agy et al., 2020a). Even within a single long se- quence, attention effectiveness degrades with dis- tance due to attention dilution, positional encoding limitations, and token interference, leading to the well-known “lost-in-the-middle” and context-decay phenomena (Liu et al., 2024; Press et al., 2021a). [URL 🔗](#page-0)

Despite their promise, current MAG systems exhibit structural and operational limitations that constrain their effectiveness in long-term reason- ing (Li et al., 2025; Chhikara et al., 2025; Xu et al., 2025; Packer et al., 2023; Rasmussen et al., 2025; Wang and Chen, 2025; Kang et al., 2025a). Most existing approaches store past interactions in mono- lithic repositories or minimally structured memory buffers, relying primarily on semantic similarity, re- cency, or heuristic scoring to retrieve relevant con- tent. For example, A-Mem (Xu et al., 2025) orga- nizes past interactions into Zettelkasten-like mem- ory units that are incrementally linked and refined, yet their retrieval pipelines rely primarily on se- mantic embedding similarity, missing the relations such as temporal or causal relationships. Cognitive- inspired frameworks like Nemori (Nan et al., 2025) [URL 🔗](#page-0)


introduce principled episodic segmentation and rep- resentation alignment, enabling agents to detect event boundaries and construct higher-level seman- tic summaries. However, their memory structures are still narrative and undifferentiated, with no ex- plicit modeling of distinct relational dimensions.

To address the structural limitations of exist- ing MAG systems, we propose MAGMA, a multi- graph agentic memory architecture that explic- itly models heterogeneous relational structure in an agent’s experience. MAGMA represents each memory item across four orthogonal relational graphs (i.e., semantic, temporal, causal, and en- tity), yielding a disentangled representation of how events, concepts, and participants are related.

Built on this unified multi-graph substrate, MAGMA introduces a hierarchical, intent-aware query mechanism that selects relevant relational views, traverses them independently, and fuses the resulting subgraphs into a compact, type-aligned context for generation. By decoupling memory rep- resentation from retrieval logic, MAGMA enables transparent reasoning paths, fine-grained control over memory selection, and improved alignment between query intent and retrieved evidence. This relational formulation provides a principled and ex- tensible foundation for agentic memory, improving both long-term coherence and interpretability.

Our contributions are summarized as follows:

- 1. We propose MAGMA, a multi-graph agentic memory architecture that explicitly models se- mantic, temporal, causal, and entity relations essential for long-horizon reasoning.

- 2. We introduce an Adaptive Traversal Policy that routes retrieval based on query intent, enabling efficient pruning of irrelevant graph regions and achieving lower latency and reduced token us- age.

- 3. We design a dual-stream memory evolution mechanism that decouples latency-sensitive event ingestion from asynchronous structural consolidation, preserving responsiveness while refining relational structure.

- 4. We demonstrate that MAGMA consistently out- performs state-of-the-art agentic memory sys- tems on long-context benchmarks including Lo- CoMo and LongMemEval, while reducing re- trieval latency and token consumption relative to prior systems. The code is open-sourced1. [URL 🔗](#page-0)

*Figure 1: High-Level Architecture of Memory- Augmented Generation (MAG).*

## 2 Background

Existing Large Language Models (LLMs) face fun- damental challenges in handling long-term agentic interactions. These challenges stem from the in- herent limitations of fixed-length contexts, which result in fragmented memory and an inability to maintain narrative coherence over time. The evo- lution of long-term consistency in LLMs is shifted from Context-Window Extension (Beltagy et al., 2020a; Press et al., 2021a; Kang et al., 2025c; [URL 🔗](#page-0)

Qian et al., 2025), [URL 🔗](#page-0)

tion (RAG) (Lewis et al., 2020; Jiang et al., 2025; Wang et al., 2024; Jiang et al., 2024; Gutiérrez et al., 2025; Lin et al., 2025) to Memory-Augmented Gen- eration (MAG). [URL 🔗](#page-0)

Retrieval-oriented approaches enrich the model with an external, dynamic memory library, giving rise to the paradigm of Memory-Augmented Gener- ation (MAG) (Zhong et al., 2024; Park et al., 2023; Huang et al., 2024). Formally, unlike static RAG, MAG maintains a time-variant memory Mt that evolves via a feedback loop: [URL 🔗](#page-0)

Retrieval-Augmented Genera-

As shown in Figure 1, this feedback loop enables the memory module to evolve over time: the user query is combined with retrieved information to form an augmented prompt, and the model’s output is subsequently written back to refine Mt. [URL 🔗](#page-0)

Some prior schemes focused on structuring the intermediate states or relationships of memory to enable better reasoning. Think-in-Memory (TiM) (Liu et al., 2023) stores evolving chains-of-thought to maintain consistency. A-MEM (Xu et al., 2025) draws inspiration from the Zettelkasten method, organizing knowledge into an interconnected note [URL 🔗](#page-0)


*Figure 2: Architectural Overview of MAGMA. The system is composed of three layers: (1) A Query Process that routes and synthesizes context; (2) A Data Structure Layer organizing memory into Relation Graphs and a Vector Database; and (3) A Write/Update Process utilizing a dual-stream mechanism for fast ingestion and asynchronous consolidation.*

network. More recently, graph-based approaches like GraphRAG (Edge et al., 2024a) and Zep (Ras- mussen et al., 2025) structure memory into knowl- edge graphs to capture cross-document dependen- cies. We provide a detailed discussion of related work in Appendix A. [URL 🔗](#page-0)

However, prior work typically organizes memory around associative proximity (e.g., semantic sim- ilarity) rather than mechanistic dependency (Kici- man et al., 2023). As a result, such methods can [URL 🔗](#page-0)

retrieve why,

what

occurred but struggle to reason about

since they lack explicit representations of

causal structure, leading to reduced accuracy in complex reasoning tasks (Jin et al., 2023; Zhang et al., 2025). [URL 🔗](#page-0)

## 3 MAGMA Design

In this section, we introduce the proposed Multi- Graph based Agentic Memory (MAGMA) design and its components in detail.

## 3.1 Architectural Overview

MAGMA architecture is organized into the fol- lowing three logical layers, orchestrating the in- teraction between control logic and the memory substrate as illustrated in Figure 2. [URL 🔗](#page-0)

Query Process: The inference engine responsi- ble for retrieving and synthesizing information. It comprises the Intent-Aware Router for dispatching tasks, the Adaptive Topological Retrieval module for executing graph traversals, and the Context Syn- thesizer for generating the final narrative response.

Data Structure (G): The unified storage substrate that fuses disparate modalities. As shown in the center of Figure 2, it maintains a Vector Database for semantic search alongside four distinct Rela- tion Graphs (i.e., Semantic, Temporal, Causal and Entity). This layer provides the topological foun- dation for cross-view reasoning. [URL 🔗](#page-0)

Write/Update Process: A dual-stream pipeline manages memory evolution. It decouples latency- sensitive operations via Synaptic Ingestion (Fast Path) from compute-intensive reasoning via Asyn- chronous Consolidation (Slow Path), ensuring the system remains responsive while continuously deepening its memory structure.

Functionally, the Query Layer interacts with the Data Structure Layer to execute the syn- chronous Query Process (Section 3.3), while the Write/Update Layer manages the continuous Mem- ory Evolution (Section 3.4). [URL 🔗](#page-0)

## 3.2 Data Structure Layer

As the core component of Memory-Augmented Generation (MAG), the data structure layer is re- sponsible for storing, organizing, and evolving past information to support future retrieval and updates. In MAGMA, we formalize this layer as a time- variant directed multigraph Gt = (Nt, Et), where nodes represent events and edges encode heteroge- neous relational structures. This unified manifold enables structured reasoning across multiple logi- cal dimensions(i.e., semantic, temporal, causal, and entity) while preserving their orthogonality.


Unified node representation: The node set N is hierarchically organized to represent experience at multiple granularities, ranging from fine-grained atomic events to higher-level episodic groupings. Each Event-Node ni ∈ Nevent is defined as:

where ci denotes the event content (e.g., obser- vations, actions, or state changes), τi is a dis- crete timestamp anchoring the event in time, and vi ∈ Rd is a dense representation indexed in the vector database (Johnson et al., 2019). The at- tribute set Ai captures structured metadata such as entity references, temporal cues, or contextual descriptors, enabling hybrid retrieval that integrates semantic similarity with symbolic and structural constraints. [URL 🔗](#page-0)

Relation graphs (edge space): The edge set E is partitioned into four semantic subspaces, corre- sponding to the relation graphs:

- Temporal Graph (Etemp): Defined as strictly ordered pairs (ni, nj) where τi < τj. This immutable chain provides the ground truth for chronological reasoning.

- Causal Graph (Ecausal): Directed edges repre- senting logical entailment. An edge eij ∈ Ecausal exists if S(nj|ni, q) > δ, explicitly inferred by the consolidation module to support "Why" queries.

- Semantic Graph (Esem): Undirected edges con- necting conceptually similar events, formally de- fined by cos(vi, vj) > θsim.

- Entity Graph (Eent): Edges connecting events to abstract entity nodes, solving the object perma- nence problem across disjoint timeline segments.

## 3.3 Query Process: Adaptive Hierarchical Retrieval

As illustrated in Figure 3, retrieval in MAGMA is formulated as a policy-guided graph traversal rather than a static lookup operation. The query process is [URL 🔗](#page-0)

orchestrated by a Router

user query into structured control signals and exe-

cutes a multi-stage retrieval pipeline (Algorithm

that dynamically selects, traverses, and fuses rele- vant relational views. Four main stages in the query process is introduced below:

Stage 1 - Query Analysis & Decomposition: The process begins by decomposing the raw user query

R, which decomposes the

1) [URL 🔗](#page-0)

q into structured control signals, including seman- tic, lexical, and temporal cues. MAGMA then ex- tracts three complementary representations to guide the retrieval process:

- Intent Classification (Tq): A lightweight clas- sifier maps q to a specific intent type Tq ∈ {WHY, WHEN, ENTITY}. This acts as the "steer- ing wheel," determining which graph edges will later be prioritized (e.g., "Why" queries trigger a bias for Causal edges).

- Temporal Parsing ([τs, τe]): A temporal tagger resolves relative expressions (e.g., "last Friday") into absolute timestamps, defining a hard time window for filtering.

- Representation Extraction: The system simul- taneously generates a dense embedding ⃗qfor se- mantic search and extracts sparse keywords qkey for exact lexical matching.

Stage 2 - Multi-Signal Anchor Identification: Before initiating graph traversal, the system first identifies a set of anchor nodes that serve as entry points into the memory graph. To ensure robustness across query modalities, we fuse signals from dense semantic retrieval, lexical keyword matching, and temporal filtering using Reciprocal Rank Fusion (RRF) (Cormack et al., 2009): [URL 🔗](#page-0)

This ensures robust starting points regardless of query modality.

Stage 3 - Adaptive Traversal Policy: Starting from the anchor set Sanchor, the system expands the context using a Heuristic Beam Search. Unlike rigid rule-based traversals, MAGMA calculates a dynamic transition score S(nj|ni, q) for moving from node ni to neighbor nj via edge eij. This score fuses structural alignment with semantic rele- vance:

Here, sim(·) denotes the cosine similarity be- tween the neighbor’s embedding and the query em-


*Figure 3: Query process with adaptive hybrid retrieval pipeline. (1) Query Analysis detects intent and fuses signals to find Anchors. (2) Adaptive Traversal navigates specific graph views (Causal, Temporal) based on the policy weights.*

## Algorithm 1 Adaptive Hybrid Retrieval (Heuristic Beam Search)

bedding. The structural alignment function ϕ dy- namically rewards edge types based on the detected query intent Tq:

```
Input: Query q, Graph G, VectorDB V, Intent Tq
Output: Narrative Context Cout
1: // Phase 1: Initialization
2: Sanchor ← RRF(V.SEARCH(⃗q),K.SEARCH(qkey)) //
Hybrid Retrieval
```

where wTq is an adaptive weight vector specific to intent Tq (e.g., assigning high weights to CAUSAL edges for "Why" queries), and 1r is the one-hot encoding of the edge relation.

```
3: CurrentFrontier, Visited ← Sanchor
4: wTq ← GETATTENTIONWEIGHTS(Tq)
5: for d ← 1 to MaxDepth do
6: Candidates ← PRIORITYQUEUE()
7: for u ∈ CurrentFrontier do
8: for v ∈ G.NEIGHBORS(u) do
```

At each step, the algorithm retains the top-k nodes with the highest cumulative scores. This ensures the traversal is guided by a dual signal: strictly following the logical structure (via ϕ) while maintaining contextual focus (via sim).

```
9: if v /∈ Visited then
10: // Calculate transition score via Eq. 5
11: suv ← exp(λ1(w⊤ Tq · 1euv ) +
λ2sim(⃗v, ⃗q))
12: scorev ← scoreu · γ + suv // Apply
Decay γ
13: Candidates.PUSH(v, scorev)
```

Stage 4: Narrative Synthesis via Graph Lin- earization: The final phase transforms the re- trieved subgraph Gsub into a coherent narrative con- text. MAGMA employs a structure-aware lineariza- tion protocol that preserves the relational depen- dencies encoded in the graph with the following three phases.

```
14: end if
15: end for
16: end for
17: CurrentFrontier ←
Candidates.TOPK(BeamWidth)
18: Visited.ADDALL(CurrentFrontier)
19: if Visited.SIZE() ≥ Budget then break
20: end if
21: end for
```

- 1. Topological Ordering: Raw nodes are reor- ganized to reflect the logic of the query. For tem- poral queries (Tq = WHEN), nodes are sorted by timestamp τi. For causal queries (Tq = WHY), we apply a topological sort on the causal edges Ecausal to ensure causes precede effects in the prompt con- text.

```
22: Csorted ← TOPOLOGICALSORT(Visited, Tq)
23: return SERIALIZE(Csorted)
```

where L denotes string concatenation.

3. Salience-Based Token Budgeting: Given a fixed LLM context window, we cannot include all retrieved nodes. We utilize the relevance scores S(nj|ni, q) computed in Eq. (5) to enforce a dy- namic budget. Low-probability nodes are summa- rized into brevity codes (e.g., "...3 intermediate events..."), while high-salience nodes retain full semantic detail.

- 2. Context Scaffolding with Provenance: To mitigate hallucination, each node is serialized into a structured block containing its timestamp, content, and explicit reference ID. We define the linearized context Cprompt as:

Cprompt = L ni∈Sort(Gsub) [<t:τi>

This structured scaffold forces the LLM to act as an interpreter of evidence rather than a creative


## Algorithm 2 Fast Path: Synaptic Ingestion

*Algorithm 3 Slow Path: Structural Consolidation*

```
Input: User Interaction I, Current Graph Gt 1: Worker Process:
Output: Updated Graph Gt+1 2: loop
1: nt ← SEGMENTEVENT(I) 3: id ← Queue.DEQUEUE()
2: nprev ← GETLASTNODE(Gt) 4: if id is null then continue
3: // Update Temporal Backbone 5: end if
4: G.ADDEDGE(nprev, nt, type = TEMP) 6: nt ← G.GETNODE(id)
5: // Indexing 7: Nlocal ← G.GETNEIGHBORHOOD(nt, hops = 2)
6: vt ← ENCODER(nt.c) 8: // Infer latent Causal and Entity structures
7: VDB.ADD(vt, nt.id) 9: Prompt ← FORMAT(Nlocal)
8: Queue.ENQUEUE(nt.id) //Trigger Slow Path 10: Enew ← ΦLLM(Prompt)
9: return nt 11: G.ADDEDGES(Enew)
```

writer, significantly reducing grounding errors.

## 3.4 Memory Evolution (Write and Update)

Long-term reasoning requires not only effective retrieval, but also a memory substrate that can adapt and reorganize as experience accumulates. MAGMA addresses this requirement through a structured memory evolution scheme that incre- mentally refines its multi-relational graph over time. Specifically, the transition from Gt to Gt+1 is governed by a dual-stream process that decouples latency-sensitive ingestion from compute-intensive consolidation (Kumaran et al., 2016), balancing short-term responsiveness with long-term reason- ing fidelity. [URL 🔗](#page-0)

Fast path ( synaptic ingestion): The Fast Path operates on the critical path of interaction, con- strained by strict latency requirements. It performs non-blocking operations: event segmentation, vec- tor indexing, and updating the immutable temporal backbone (nt−1 → nt). As detailed in Algorithm 2, no blocking LLM reasoning occurs here, ensuring the agent remains responsive regardless of memory size. [URL 🔗](#page-0)

Slow path (structural consolidation): Asyn- chronously, the slow path performs Memory Con- solidation (Algorithm 3). It functions as a back- ground worker that dequeues events and densifies the graph structure. By analyzing the local neigh- borhood N(nt) of recent events, the system em- ploys an LLM Φ to infer latent connections: [URL 🔗](#page-0)

This process constructs high-value Ecausal and Eent links, effectively trading off compute time for rela- tional depth.

## 3.5 Implementation

We implement MAGMA as a modular three-layer architecture designed for extensibility, scalability,

```
12: end loop
```

and deployment flexibility. The storage layer ab- stracts over heterogeneous physical backends, pro- viding unified interfaces for managing the typed memory graph, dense vector indices, and sparse keyword indices. This abstraction cleanly separates the logical memory model from its physical real- ization, enabling seamless substitution of storage backends (e.g., in-memory data structures versus production-grade graph or vector databases) with minimal engineering effort.

The retrieval layer coordinates the core algo- rithmic components, including memory construc- tion, multi-stage ranking, and policy-guided graph traversal. It is supported by specialized utility modules for episodic segmentation and temporal normalization, which provide structured signals to downstream retrieval and traversal policies. The ap- plication layer manages the interaction loop, evalu- ation harnesses, and prompt construction, serving as the interface between the agent and the underly- ing memory system.

## 4 Experiments

We conduct comprehensive experiments to evalu- ate both the reasoning effectiveness and systems properties of the proposed MAGMA architecture over state-of-the-art baselines.

## 4.1 Experimental Setup

Datasets. We evaluate long-term conversational capability using two widely adopted benchmarks: (1) LoCoMo (Maharana et al., 2024): which con- tains ultra-long conversations (average length of 9K tokens) designed to assess long-range temporal and causal retrieval. (2) LongMemEval (Wu et al., 2024): a large-scale stress-test benchmark with an average context length exceeding 100K tokens, used to evaluate scalability and memory retention stability over extended interaction horizons.. [URL 🔗](#page-0)


*Table 1: Performance on the LoCoMo benchmark evaluated using the LLM-as-a-Judge metric. Higher scores indicate better performance. LLM model is based on gpt-4o-mini.*

| Method |   |   |   |   |   | Multi-Hop Temporal Open-Domain Single-Hop Adversarial Overall |
| --- | --- | --- | --- | --- | --- | --- |
| Full Context | 0.468 | 0.562 | 0.486 | 0.630 | 0.205 | 0.481 |
| A-MEM | 0.495 | 0.474 | 0.385 | 0.653 | 0.616 | 0.580 |
| MemoryOS | 0.552 | 0.422 | 0.504 | 0.674 | 0.428 | 0.553 |
| Nemori | 0.569 | 0.649 | 0.485 | 0.764 | 0.325 | 0.590 |
| MAGMA (ours) | 0.528 | 0.650 | 0.517 | 0.776 | 0.742 | 0.700 |

Baselines. We compare MAGMA against four state-of-the-art memory architectures. For fair com- parison, all methods employ the same backbone LLMs.

- Full Context: Feeds the entire conversation his- tory into the LLM.

- A-MEM (Xu et al., 2025): A biological-inspired, self-evolving memory system that dynamically organizes agent experiences. [URL 🔗](#page-0)

- Nemori (Nan et al., 2025): A graph-based mem- ory utilizing a "predict-calibrate" mechanism for episodic segmentation. [URL 🔗](#page-0)

- MemoryOS(Kang et al., 2025a) : A semantic- focused memory operating system employing a hierarchical storage strategy. [URL 🔗](#page-0)

Metrics. Following standard evaluation protocols, we primarily use the LLM-as-a-Judge score (Zheng et al., 2023) to assess the accuracy of different methods. The detailed evaluation prompt used for the judge model is provided in the appendix. For completeness, we also report token-level F1 and BLEU-1 (Papineni et al., 2002). [URL 🔗](#page-0)

## 4.2 Overall Comparison

This section introduces the accuracy performance comparison between all methods on the LoCoMo benchmark based on LLM-as-a-judge. As shown in Table 1, MAGMA achieves the highest over- all judge score of 0.7, substantially outperforming the other baselines: Full Context (0.481), A-MEM (0.58), MemoryOS (0.553) and Nemori (0.59) by relative margins of 18.6% to 45.5%. This re- sult demonstrates that explicitly modeling multi- relational structure enables more accurate long- horizon reasoning than flat or purely semantic mem- ory architectures. [URL 🔗](#page-0)

A closer analysis reveals that MAGMA’s ad- vantage is particularly pronounced in reasoning- intensive settings. In the Temporal category, MAGMA slightly but consistently outperforms oth- ers (Judge: 0.650 for MAGMA vs. 0.422 - 0.649 for

others), validating the effectiveness of our Tempo- ral Inference Engine in resolving relative temporal expressions into grounded chronological represen- tations. The performance gap further widens under adversarial conditions, where MAGMA attains a judge score of 0.742. This robustness stems from the Adaptive Traversal Policy, which prioritizes causal and entity-consistent paths and avoids se- mantically similar yet structurally irrelevant dis- tractors that often mislead vector-based retrieval systems. Additional results and analyzes, includ- ing case studies and evaluations under alternative metrics, are provided in the appendix.

## 4.3 Generalization Study

To evaluate generalization under extreme context lengths, we compare MAGMA against prior meth- ods on the LongMemEval benchmark. Long- MemEval poses a substantial scalability challenge, with an average context length exceeding 100k to- kens, and therefore serves as a rigorous stress test for long-term memory retention and retrieval under strict computational constraints.

As summarized in Table 2, MAGMA achieves the highest average accuracy (61.2%), outperform- ing both the Full-context baseline (55.0%) and the Nemori system (56.2%). These results indicate that MAGMA generalizes effectively to ultra-long inter- action histories while maintaining strong retrieval precision. [URL 🔗](#page-0)

At the same time, the results highlight a favor- able efficiency–granularity trade-off. Although the Full-context baseline performs strongly on single- session-assistant tasks (89.3%), this performance comes at a prohibitive computational cost, requir- ing over 100k tokens per query. MAGMA achieves competitive accuracy (83.9%) while using only 0.7k–4.2k tokens per query, representing a reduc- tion of more than 95%. This demonstrates that MAGMA effectively compresses long interaction histories into compact, reasoning-dense subgraphs, preserving essential information while substantially


*Table 2: Performance comparison on LongMemEval dataset across different question types. We compare our MAGMA method against the Full-context baseline and the Nemori system.*

| Question Type | Full-context | Nemori | MAGMA |
| --- | --- | --- | --- |
|   | (101K tokens) (3.7–4.8K tokens) (0.7–4.2K tokens) |   |   |
| single-session-preference | 6.7% | 62.7% | 73.3% |
| single-session-assistant gpt-4o-mini | 89.3% | 73.2% | 83.9% |
| temporal-reasoning | 42.1% | 43.0% | 45.1% |
| multi-session | 38.3% | 51.4% | 50.4% |
| knowledge-update | 78.2% | 52.6% | 66.7% |
| single-session-user | 78.6% | 77.7% | 72.9% |
| Average | 55.0% | 56.2% | 61.2% |

*Table 3: System efficiency comparison with total mem- ory build time (in hours), average token consumption per query (in k tokens), and average query latency (in seconds).*

| Method Build Time (h) Tokens/Query (k) Latency (s) |   |   |   |
| --- | --- | --- | --- |
| Full Context N/A |   | 8.53 | 1.74 |
| A-MEM | 1.01 | 2.62 | 2.26 |
| MemoryOS | 0.91 | 4.76 | 32.68 |
| Nemori | 0.29 | 3.46 | 2.59 |
| MAGMA | 0.39 | 3.37 | 1.47 |

*Table 4: Breakdown analysis on the performance impact of different schemes in MAGMA.*

| MAGMA schemes | Judge F1 BLEU-1 |
| --- | --- |
| w/o Adaptive Policy | 0.637 0.413 0.357 |
| w/o Causal Links | 0.644 0.439 0.354 |
| w/o Temporal Backbone 0.647 0.438 0.349 |   |
| w/o Entity Links | 0.666 0.451 0.363 |
| MAGMA (Full) | 0.700 0.467 0.378 |

reducing inference-time overhead.

## 4.4 System Efficiency Analysis

To evaluate the system efficiency of MAGMA, two metrics are focused: (1) memory build time (the time required to construct the memory graph) and (2) token cost (the average tokens processed per query).

Table 3 reports the comparative results. While A-MEM achieves the lowest token consumption (2.62k) due to its aggressive summarization, it sac- rifices reasoning depth (see Table 1). In contrast, MAGMA achieves the lowest query latency (1.47s) about 40% faster than the next best retrieval base- line (A-MEM) while maintaining a competitive token cost (3.37k). This efficiency stems from our Adaptive Traversal Policy, which prunes irrelevant subgraphs early, and the dual-stream architecture that offloads complex indexing to the background. [URL 🔗](#page-0)

## 4.5 Ablation Study

In this subsection, we conduct a systematic abla- tion study to assess the contribution of individual components in MAGMA. By selectively disabling edge types and traversal mechanisms, we isolate the sources of its reasoning capability. The results in Table 4 reveal three main findings. [URL 🔗](#page-0)

First, removing Traversal Policy results in the largest performance drop, with the Judge score de- creasing from 0.700 to 0.637. This confirms that intent-aware routing is critical: without it, retrieval degenerates into a static graph walk that introduces structurally irrelevant information and degrades rea- soning quality. Second, removing either Causal Links or the Temporal Backbone leads to compara- ble and substantial performance losses (0.644 and 0.647, respectively), indicating that causal struc- ture and temporal ordering provide complemen- tary, non-substitutable axes of reasoning. Finally, removing Entity Links causes a smaller but con- sistent decline (0.700 to 0.666), highlighting their role in maintaining entity permanence and reducing hallucinations in entity-centric queries.

## 5 Conclusion

We introduced MAGMA, a multi-graph agentic memory architecture that models semantic, tem- poral, causal, and entity relations within a uni- fied yet disentangled memory substrate. By for- mulating retrieval as a policy-guided graph traver- sal and decoupling memory ingestion from asyn- chronous structural consolidation, MAGMA en- ables effective long-horizon reasoning while main- taining low inference-time latency. Empirical re- sults on LoCoMo and LongMemEval demonstrate that MAGMA consistently outperforms state-of- the-art memory systems while achieving substan- tial efficiency gains under ultra-long contexts.


## 6 Limitations

While MAGMA demonstrates strong empirical per-

formance, it has several limitations. First, the qual- ity of the constructed memory graph depends on the reasoning fidelity of the underlying Large Lan- guage Models used during asynchronous consoli- dation. This dependency is a shared limitation of agentic memory systems that rely on LLM-based structural inference, as they are susceptible to ex- traction errors and hallucinations (Pan et al., 2024; Xi et al., 2025; Wadhwa et al., 2023). Although MAGMA employs structured prompts and conser- vative inference thresholds to reduce spurious links, erroneous or missing relations may still arise and propagate to downstream retrieval. Nevertheless, our experimental results indicate that, even under these constraints, agentic memory systems such as MAGMA substantially outperform traditional base- lines, including full-context approaches, in long- horizon reasoning tasks. [URL 🔗](#page-0)

Second, multi-graph substrate may introduce ad- ditional storage and engineering complexity com- pared to flat, vector-only memory systems. Main- taining multiple relational views and dual-stream processing incurs a little higher implementation and memory overhead, which may limit applicabil- ity in highly resource-constrained environments.

Finally, most existing agentic memory systems, including MAGMA, are primarily evaluated on long-context conversational and agentic bench- marks such as LoCoMo and LongMemEval. While these benchmarks effectively stress temporal and causal reasoning, they do not cover the full range of settings in which agentic memory may be re- quired(Hu et al., 2025). Extending MAGMA to other scenarios, such as multimodal agents or envi- ronments with heterogeneous observation streams, may require additional adaptation and calibration. Addressing these broader evaluation settings re- mains an important research direction for future work. [URL 🔗](#page-0)

## References

Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Altman, Shyamal Anadkat, and 1 others. 2023. Gpt-4 techni- cal report. arXiv preprint arXiv:2303.08774.

Iz Beltagy, Matthew E Peters, and Arman Cohan. 2020a. Longformer: The long-document transformer. arXiv preprint arXiv:2004.05150.

Iz Beltagy, Matthew E Peters, and Arman Cohan. 2020b. Longformer: The long-document transformer. arXiv preprint arXiv:2004.05150.

Tom Brown, Benjamin Mann, Nick Ryder, Melanie Subbiah, Jared D Kaplan, Prafulla Dhariwal, Arvind Neelakantan, Pranav Shyam, Girish Sastry, Amanda Askell, and 1 others. 2020. Language models are few-shot learners. Advances in neural information processing systems, 33:1877–1901.

Prateek Chhikara, Dev Khant, Saket Aryan, Taranjeet Singh, and Deshraj Yadav. 2025. Mem0: Building production-ready ai agents with scalable long-term memory. arXiv preprint arXiv:2504.19413.

Gordon V. Cormack, Charles L A Clarke, and Stefan Buettcher. 2009. Reciprocal rank fusion outperforms condorcet and individual rank learning methods. In Proceedings ofthe 32nd International ACM SIGIR Conference on Research and Development in Infor- mation Retrieval, SIGIR ’09, page 758–759, New York, NY, USA. Association for Computing Machin- ery. [URL 🔗](https://doi.org/10.1145/1571941.1572114)

Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Dasha Metropolitansky, Robert Osazuwa Ness, and Jonathan Larson. 2024a. From local to global: A graph rag approach to query-focused summarization. arXiv preprint arXiv:2404.16130.

Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Dasha Metropolitansky, Robert Osazuwa Ness, and Jonathan Larson. 2024b. From local to global: A graph rag approach to query-focused summarization. arXiv preprint arXiv:2404.16130.

Bernal Jiménez Gutiérrez, Yiheng Shu, Weijian Qi, Sizhe Zhou, and Yu Su. 2025. From rag to memory: Non-parametric continual learning for large language models. arXiv preprint arXiv:2502.14802.

Yuyang Hu, Shichun Liu, Yanwei Yue, Guibin Zhang, Boyang Liu, Fangyi Zhu, Jiahang Lin, Honglin Guo, Shihan Dou, Zhiheng Xi, and 1 others. 2025.

Memory in the age of ai agents. arXiv:2512.13564.

arXiv preprint

Le Huang, Hengzhi Lan, Zijun Sun, Chuan Shi, and Ting Bai. 2024. Emotional rag: Enhancing role- playing agents through emotional retrieval. In 2024 IEEE International Conference on Knowledge Graph (ICKG), pages 120–127. IEEE.

Wenqi Jiang, Suvinay Subramanian, Cat Graves, Gus- tavo Alonso, Amir Yazdanbakhsh, and Vidushi Dadu. 2025. Rago: Systematic performance optimization for retrieval-augmented generation serving. In Pro- ceedings of the 52nd Annual International Sympo- sium on Computer Architecture, pages 974–989.

Ziyan Jiang, Xueguang Ma, and Wenhu Chen. 2024. Longrag: Enhancing retrieval-augmented gener- ation with long-context llms. arXiv preprint arXiv:2406.15319.


- Zhijing Jin, Yuen Chen, Felix Leeb, Luigi Gresele, Ojasv Kamal, Zhiheng Lyu, Kevin Blin, Fernando Gonzalez Adauto, Max Kleiman-Weiner, Mrinmaya Sachan, and 1 others. 2023. Cladder: Assessing causal reasoning in language models. Advances in Neural Information Processing Systems, 36:31038– 31065.

- Jeff Johnson, Matthijs Douze, and Hervé Jégou. 2019. Billion-scale similarity search with gpus. IEEE Transactions on Big Data, 7(3):535–547.

- Jiazheng Kang, Mingming Ji, Zhe Zhao, and Ting Bai. 2025a. Memory os of ai agent. arXiv preprint arXiv:2506.06326.

- Jiazheng Kang, Mingming Ji, Zhe Zhao, and Ting Bai. 2025b. Memory os of ai agent. arXiv preprint arXiv:2506.06326.

- Jikun Kang, Wenqi Wu, Filippos Christianos, Alex J Chan, Fraser Greenlee, George Thomas, Marvin Pur- torab, and Andy Toulis. 2025c. Lm2: Large memory models. arXiv preprint arXiv:2502.06049.

- Urvashi Khandelwal, He He, Peng Qi, and Dan Ju- rafsky. 2018. Sharp nearby, fuzzy far away: How neural language models use context. arXiv preprint arXiv:1805.04623.

- Emre Kiciman, Robert Ness, Amit Sharma, and Chen- hao Tan. 2023. Causal reasoning and large language models: Opening a new frontier for causality. Trans- actions on Machine Learning Research.

- Dharshan Kumaran, Demis Hassabis, and James L Mc- Clelland. 2016. What learning systems do intelligent agents need? complementary learning systems the- ory updated. Trends in cognitive sciences, 20(7):512– 534.

- Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Hein- rich Küttler, Mike Lewis, Wen-tau Yih, Tim Rock- täschel, and 1 others. 2020. Retrieval-augmented gen- eration for knowledge-intensive nlp tasks. Advances in neural information processing systems, 33:9459– 9474.

- Zhiyu Li, Shichao Song, Chenyang Xi, Hanyu Wang, Chen Tang, and 1 others. 2025. Memos: A memory os for ai system. arXiv preprint arXiv:2507.03724.

- Shuhang Lin, Zhencan Peng, Lingyao Li, Xiao Lin, Xi Zhu, and Yongfeng Zhang. 2025. Cache mech- anism for agent rag systems. arXiv preprint arXiv:2511.02919.

- Lei Liu, Xiaoyan Yang, Yue Shen, Binbin Hu, Zhiqiang Zhang, Jinjie Gu, and Guannan Zhang. 2023. Think- in-memory: Recalling and post-thinking enable llms with long-term memory. arXiv preprint arXiv:2311.08719.

- Nelson F Liu, Kevin Lin, John Hewitt, Ashwin Paran- jape, Michele Bevilacqua, Fabio Petroni, and Percy Liang. 2024. Lost in the middle: How language mod- els use long contexts. Transactions ofthe Association for Computational Linguistics, 12:157–173.

- Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal, Francesco Barbieri, and Yuwei Fang. 2024. Evaluating very long-term conver- sational memory of llm agents. arXiv preprint arXiv:2402.17753.

- Jiayan Nan, Wenquan Ma, Wenlong Wu, and Yize Chen. 2025. Nemori: Self-organizing agent mem- ory inspired by cognitive science. arXiv preprint arXiv:2508.03341.

- Charles Packer, Vivian Fang, Shishir_G Patil, Kevin Lin, Sarah Wooders, and Joseph_E Gonzalez. 2023. Memgpt: Towards llms as operating systems.

- Shirui Pan, Linhao Luo, Yufei Wang, Chen Chen, Ji- apu Wang, and Xindong Wu. 2024. Unifying large language models and knowledge graphs: A roadmap. IEEE Transactions on Knowledge and Data Engi- neering, 36(7):3580–3599.

- Kishore Papineni, Salim Roukos, Todd Ward, and Wei- Jing Zhu. 2002. Bleu: a method for automatic evalu- ation of machine translation. In Proceedings ofthe 40th Annual Meeting ofthe Association for Compu- tational Linguistics, pages 311–318, Philadelphia, Pennsylvania, USA. Association for Computational Linguistics. [URL 🔗](https://doi.org/10.3115/1073083.1073135)

- Joon Sung Park, Joseph O’Brien, Carrie Jun Cai, Mered- ith Ringel Morris, Percy Liang, and Michael S Bern- stein. 2023. Generative agents: Interactive simulacra of human behavior. In Proceedings of the 36th an- nual acm symposium on user interface software and technology, pages 1–22.

- Ofir Press, Noah A Smith, and Mike Lewis. 2021a. Train short, test long: Attention with linear biases enables input length extrapolation. arXiv preprint arXiv:2108.12409.

- Ofir Press, Noah A Smith, and Mike Lewis. 2021b. Train short, test long: Attention with linear biases enables input length extrapolation. arXiv preprint arXiv:2108.12409.

- Hongjin Qian, Zheng Liu, Peitian Zhang, Kelong Mao, Defu Lian, Zhicheng Dou, and Tiejun Huang. 2025. Memorag: Boosting long context processing with global memory-enhanced retrieval augmentation. In Proceedings of the ACM on Web Conference 2025, pages 2366–2377.

- Preston Rasmussen, Pavlo Paliychuk, Travis Beauvais, Jack Ryan, and Daniel Chalef. 2025. Zep: a tempo- ral knowledge graph architecture for agent memory. arXiv preprint arXiv:2501.13956.


- Somin Wadhwa, Silvio Amir, and Byron C Wallace. 2023. Revisiting relation extraction in the era of large language models. In Proceedings ofthe conference. association for computational linguistics. meeting, volume 2023, page 15566.

- Yu Wang and Xi Chen. 2025. Mirix: Multi-agent mem- ory system for llm-based agents. arXiv preprint arXiv:2507.07957.

- Zheng Wang, Shu Teo, Jieer Ouyang, Yongjun Xu, and Wei Shi. 2024. M-rag: Reinforcing large language model performance through retrieval-augmented gen- eration with multiple partitions. In Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers), pages 1966–1978.

- Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Fei Xia, Ed Chi, Quoc V Le, Denny Zhou, and 1 others. 2022. Chain-of-thought prompting elic- its reasoning in large language models. Advances in neural information processing systems, 35:24824– 24837.

- Di Wu, Hongwei Wang, Wenhao Yu, Yuwei Zhang, Kai-Wei Chang, and Dong Yu. 2024. Longmemeval: Benchmarking chat assistants on long-term interac- tive memory. arXiv preprint arXiv:2410.10813.

- Zhiheng Xi, Wenxiang Chen, Xin Guo, Wei He, Yi- wen Ding, Boyang Hong, Ming Zhang, Junzhe Wang, Senjie Jin, Enyu Zhou, and 1 others. 2025. The rise and potential of large language model based agents: A survey. Science China Information Sci- ences, 68(2):121101.

- Wujiang Xu, Zujie Liang, Kai Mei, Hang Gao, Jun- tao Tan, and Yongfeng Zhang. 2025. A-mem: Agentic memory for llm agents. arXiv preprint arXiv:2502.12110.

- Zhuosheng Zhang, Yao Yao, Aston Zhang, Xiangru Tang, Xinbei Ma, Zhiwei He, Yiming Wang, Mark Gerstein, Rui Wang, Gongshen Liu, and 1 others. 2025. Igniting language intelligence: The hitch- hiker’s guide from chain-of-thought reasoning to lan- guage agents. ACM Computing Surveys, 57(8):1–39.

- Lianmin Zheng, Wei-Lin Chiang, Ying Sheng, Siyuan Zhuang, Zhanghao Wu, Yonghao Zhuang, Zi Lin, Zhuohan Li, Dacheng Li, Eric Xing, and 1 others. 2023. Judging llm-as-a-judge with mt-bench and chatbot arena. Advances in neural information pro- cessing systems, 36:46595–46623.

- Wanjun Zhong, Lianghong Guo, Qiqi Gao, He Ye, and Yanlin Wang. 2024. Memorybank: Enhancing large language models with long-term memory. In Pro- ceedings ofthe AAAI Conference on Artificial Intelli- gence, volume 38, pages 19724–19731.


## A Related Work

Following the framing in main text, we organize related work along the same progression: from context window extension to retrieval augmented generation (RAG) and finally to memory aug- mented generation (MAG), and then discuss struc- tured/graph memories and causal reasoning, which are central to long-horizon agentic interactions.

Context-window Extension. A direct line of work extends the effective context length of Transform- ers by modifying attention or positional extrap- olation. Longformer (Beltagy et al., 2020b) in- troduces sparse attention patterns to scale to long documents, reducing quadratic cost while retain- ing locality and selected global connectivity. AL- [URL 🔗](#page-0)

iBi (Press et al., 2021b) [URL 🔗](#page-0)

Biases) enables length extrapolation by injecting distance-aware linear biases into attention scores, improving robustness when testing on longer se- quences than those seen in training. Recent efforts also add explicit memory modules or hybrid mech- anisms to push beyond pure attention-window scal- ing. For example, LM2 (Kang et al., 2025c) pro- poses a decoder-only architecture augmented with an auxiliary memory to mitigate long-context lim- itations. MemoRAG (Qian et al., 2025) similarly emphasizes global-memory-enhanced retrieval to boost long-context processing when raw context is insufficient or inefficient. While these approaches improve long-range coverage, they do not, by them- selves, address the continual, evolving, and write- back nature of agent memory required for multi- session interactions. [URL 🔗](#page-0)

Retrieval Augmented Generation. RAG (Lewis et al., 2020) augments an LLM with external re- trieval over a fixed corpus, classically retrieving supporting passages and conditioning generation on them. Subsequent work explores better inte- gration with long-context models and more scal- able retrieval pipelines. LongRAG (Jiang et al., 2024) studies how to exploit long-context LLMs together with retrieval, improving the ability to incorporate larger retrieved evidence sets. Other systems focus on structuring the retrieved memory space or optimizing the RAG serving stack: M- RAG (Wang et al., 2024) uses multiple partitions to encourage fine-grained retrieval focus, while RAGO (Jiang et al., 2025) provides a systematic framework for performance optimization in RAG serving. However, standard RAG typically assumes a static knowledge base. In contrast, agentic set- [URL 🔗](#page-0)

(Attention with Linear

tings require memory that is continuously updated (the feedback loop described in the main text). This motivates the shift to MAG systems, where mem- ory is dynamic and evolves with interaction histo- ries.

Memory Augmented Generation and Agent Memory Systems. MAG systems maintain and up- date an external memory over time, enabling agents to accumulate knowledge, preserve identity, and re- main coherent across sessions. Early and represen- tative directions include memory construction and write-back strategies for long-term agent behav- ior, such as MemoryBank (Zhong et al., 2024) and generative agents style architectures that empha- size persistent profiles and evolving state grounded in past interactions (Nan et al., 2025; Maharana et al., 2024). A growing body of work adopts sys- tems metaphors and designs: MemGPT (Packer et al., 2023) frames LLM agents with an operating- system-like memory hierarchy, emphasizing pag- ing and controlled context management. More re- cent memory OS systems propose explicit storage hierarchies and controllers (e.g., MemoryOS (Kang et al., 2025b), MemOS (Li et al., 2025)) to manage persistence and retrieval policies at scale. In addi- tion, practical agent-memory stacks (e.g., Zep (Ras- mussen et al., 2025)) offer temporal knowledge- graph-based memory services aimed at real-world deployment constraints. [URL 🔗](#page-0)

Structured memory: chains-of-thought and graph-based representations. Beyond flat text buffers or vector stores, several methods explicitly structure memory to support reasoning. Think-in- Memory (TiM) stores evolving chains-of-thought to improve consistency across long-horizon reason-

ing, while A-MEM

(Xu et al., 2025) [URL 🔗](#page-0)

is inspired

by Zettelkasten-style linking of notes/experiences. These methods highlight the value of represent- ing intermediate reasoning traces or explicit links, but many retrieval pipelines still predominantly rely on semantic similarity as the primary access mechanism. Graph-based approaches have recently gained traction as a way to capture cross-document and cross-episode dependencies. GraphRAG (Edge et al., 2024b) builds entity-centric graphs and com- munity summaries to answer more global questions over large corpora. Zep proposes a temporally- aware knowledge-graph engine (Graphiti) that syn- thesizes conversational and structured business data while preserving historical relations. The main text notes these graph-based lines explicitly and mo- tivates a key gap: many systems organize mem- [URL 🔗](#page-0)


ory around associative proximity (semantic related- ness) rather than mechanistic dependency.

## Causal reasoning and long-horizon evaluation.

Causal reasoning has been highlighted as both im- portant and challenging for LLMs. The work (Kici- man et al., 2023) study LLMs’ ability to generate causal arguments across multiple causal tasks and emphasize robustness/failure modes, reinforcing that what happened retrieval is not sufficient for why reasoning in many settings. Benchmarking efforts such as LoCoMo (Maharana et al., 2024) stress long-range temporal and causal dynamics in multi-session conversations and provide evaluation tasks that expose long-horizon memory deficits. The paper’s experimental setup also uses Long- MemEval (Wu et al., 2024) as an ultra-long context stress test, and evaluates via LLM-as-a-Judge proto- cols standard in modern instruction-following eval- uation. Overall, prior work demonstrates steady progress in (i) scaling context length, (ii) improv- ing retrieval pipelines, and (iii) building struc- tured, evolving memories for agents. The main text positions MAGMA within this trajectory by explicitly targeting multi-relational structure (se- mantic/temporal/causal/entity) and intent-aware re- trieval control. [URL 🔗](#page-0)

## B System Implementation Details

## B.1 Hyperparameter Configuration

Table 5 presents the comprehensive configuration used in our experiments. These parameters were empirically optimized on the LoCoMo benchmark. Notably, MAGMA employs an Adaptive Scoring mechanism where weights (λ) shift dynamically based on the detected query intent. [URL 🔗](#page-0)

## C Prompt Library

MAGMA employs a sophisticated prompt strategy with three distinct types, each optimized for spe- cific cognitive tasks within the memory pipeline.

## C.1 Event Extraction Prompt (JSON-Structured)

To ensure robustness against hallucination and pars- ing errors, this module employs a strict JSON schema enforcement strategy. The prompt explic- itly defines the extraction targets to ensure down- stream graph integrity, capturing not just entities but also semantic relationships and temporal mark- ers.

Table 5: Hyperparameter settings for MAGMA. "Traver- sal Weights" correspond to the intent-specific vector wTq , while λ1 and λ2 control the global balance be- tween structural alignment and semantic affinity (Eq. 5). [URL 🔗](#page-0)

| Module | Parameter | Value/Range |
| --- | --- | --- |
|   | Model (Default) | all-MiniLM-L6-v2 |
| Embedding | Model (Optional) | text-embedding-3-small |
|   | Dimension | 384 / 1536 |
| Inference | LLM Backbone | gpt-4o-mini |
|   | Temperature | 0.0 |
|   | RRF Constant (k) 60 |   |
| Retrieval (Phase 1) | Vector Top-K | 20 |
|   | wkeyword (Fusion) 2.0 – 5.0 |   |
|   | Sim. Threshold | 0.10–0.30 |
|   | Max Depth | 5 hops |
| Traversal (Phase 2) | Max Nodes | 200 |
|   | Drop Threshold | 0.15 |
|   | λ1 (Structure Coef.) 1.0 (Base) |   |
|   | λ2 (Semantic Coef.) 0.3 – 0.7 |   |
| Adaptive Weights | wentity (in wTq ) | 2.5 – 6.0 |
| (Eq. ??) | wtemporal (in wTq ) 0.5 – 4.0 |   |
|   | wcausal (in wTq ) | 3.0 – 5.0 |
|   | wphrase (in wTq ) | 2.5 – 5.0 |

## System Prompt: Event Extractor

System Role: You are an automated Graph Memory Parser. Your task is to extract structured metadata from raw conversational logs to build a knowledge graph.

- Speaker: {speaker}

- Text: {text}

- Context: {prev_summary}

Instructions: Analyze the input and return ONLY a valid JSON object matching the specific schema below. Do not include markdown formatting.

- "entities": List of proper nouns (People, Locations, Organizations).

- "topic": String (1–3 words representing the main theme).

- "relationships": List of strings describing interactions (e.g., "X researches Y").

- "semantic_facts": List of atomic facts preserving key information.

- "dates_mentioned": List of temporal strings (e.g., "next Friday", "2024-01-01").

- "summary": One-sentence summary preserving speaker attribution.

## Input Data:

## Target Schema:

## C.2 Query-Adaptive QA Prompt

The generation prompt begins with a strict persona definition and appends specific reasoning instruc- tions dynamically based on the Router’s classifica- tion (e.g., Multi-hop, Temporal, Open-domain).

## System Prompt: Adaptive QA

System Role: You are a precision QA assistant operating on retrieved memory contexts. Your goal is to answer the user’s question accurately using only the provided information.

Context: {context}


## Current Query:

- Question: {question}

- Constraints: {category_specific_constraints} Instructions:

- 1. Use ONLY information explicitly stated in the context.

- 2. If the answer is not present, respond exactly with "Information not found".

- 3. Be concise (typically 1–10 words) unless detailed reasoning is required.

- 4. {dynamic_instruction} // Automatically generated by our engine’s query classifier/router (no oracle labels)

## Answer:

## *Dynamic Instruction Injection Candi- dates:

- [Multi-hop]: "Connect related facts across different nodes. For comparison queries (e.g., ’both/all’), identify com- monalities between entities rather than listing individual details."

- [Temporal]: "Resolve relative dates (e.g., ’yesterday’) using the event timestamps. Output dates strictly in ’D Month YYYY’ format. Calculate durations if asked."

- [Open-Domain/Inference]: "Make reasonable inferences based on the user’s personality traits, interests, and past behaviors. Support hypotheti- cal (’would/could’) reasoning with evidence."

- [Single-hop/Factual]: "Extract the spe- cific entity, name, or method requested. Do not add explanations. Return the ex- act fact matching the query intent."

## C.3 Evaluation Prompt (LLM-as-a-Judge)

To ensure rigorous evaluation beyond simple n- gram overlapping, we employ a semantic scor- ing mechanism. The Judge LLM evaluates the alignment between the generated response and the ground truth using the following schema.

## System Prompt: Semantic Grader

You are an expert evaluator assessing the semantic fidelity of a memory retrieval system. Score the Candidate Answer against the Gold Reference on a continuous scale [0.0, 1.0].

- 1.0 (Exact Alignment): Captures all key entities, temporal markers, and causal relationships. Semantically equivalent.

- 0.8 (Substantially Correct): Main point is accurate but lacks minor nuances or secondary details.

## Scoring Rubric:

- 0.6 (Partial Match): Contains valid information but misses key constraints (e.g., wrong date but correct event).

- 0.4 (Tangential): Touches on the topic but misses the core information requirement.

- 0.2 (Incoherent): Factually incorrect with only minimal topical overlap.

- 0.0 (Contradiction/Hallucination): Completely unrelated or contradicts the ground truth.

## Evaluation Constraints:

- 1. Temporal Flexibility: Accept relative time references (e.g., "next Tuesday") if they resolve to the same period as the Gold Reference.

- 2. Semantic Equivalence: Prioritize informational content over lexical matching.

- 3. Adversarial Handling: If the Gold Reference states "Unanswerable", the Candidate MUST explicitly state lack of information. Any hallucinated fact results in 0.0.

Input: Question: {question} | Gold: {gold} | Candidate: {generated} Output: JSON {"score": float, "reasoning":

"concise explanation"}

## D Baseline Configurations

To ensure a fair and rigorous comparison, we stan- dardized the experimental environment across all systems. Specifically, we adhered to the following protocols:

- Full Context Baseline: We implemented a "Full Context" baseline where the entire avail- able conversation history is fed directly into the LLM’s context window (up to the 128k token limit of gpt-4o-mini). This serves as a "brute-force" reference to evaluate the model’s native long-context capabilities with- out external retrieval mechanisms.

- Retrieval-Based Baselines: For all baseline systems (e.g., AMem, Nemori, MemoryOS), we applied their official default hyperparam- eters and storage settings to reflect their stan- dard out-of-the-box performance.

- Unified Backbone Model: To eliminate per- formance variance caused by different foun- dation models, all systems utilized OpenAI’s gpt-4o-mini for both retrieval reasoning and response generation.

- Unified Evaluation: All system outputs were evaluated using the identical LLM-as-a-Judge framework (also powered by gpt-4o-mini with temperature=0.0), as detailed in Ap- pendix C. [URL 🔗](#page-0)


Dataset Statistics. We conducted a comprehen- sive evaluation on the full LoCoMo benchmark, testing across all five cognitive categories to assess varying levels of retrieval complexity. The detailed distribution of query types is presented in Table 6. [URL 🔗](#page-0)

*Table 6: Distribution of query categories in the LoCoMo benchmark used for evaluation.*

| Query Category | Count |
| --- | --- |
| Single-Hop Retrieval | 841 |
| Adversarial | 446 |
| Temporal Reasoning | 321 |
| Multi-Hop Reasoning 282 |   |
| Open Domain | 96 |
| Total Samples | 1,986 |

## E Case Study

To demonstrate MAGMA’s reasoning capabili- ties across different cognitive modalities, we ana- lyze three real-world scenarios from the LoCoMo benchmark. Table 7 provides a side-by-side com- parison of MAGMA against key baselines (A- MEM, Nemori, MemoryOS). [URL 🔗](#page-0)

## E.1 Detailed Analysis

Case 1: Overcoming Information Loss (Re- call). For the query regarding instruments, A- MEM failed completely due to its summarization process abstracting away specific details ("violin") from early sessions. Other RAG baselines only re- trieved the "clarinet" due to surface-level semantic matching. MAGMA, however, maintains an entity- centric graph structure. Instead of relying on rigid schemas, MAGMA queries the local neighborhood of the [Entity: Melanie] node. This allows it to capture diverse natural language predicates (e.g., "playing my violin", "started clarinet") and aggre- gate disjoint facts into a comprehensive answer, demonstrating robustness against information loss.

Case 2: Multi-Hop Reasoning vs. Surface Ex- traction. The query "How many children?" ex- poses a critical weakness in standard RAG: the inability to perform arithmetic across contexts. Baselines simply extracted the explicit mention of "two children" from a photo caption. In contrast, MAGMA treated this as a graph traversal problem focused on entity resolution. It queried the neigh- borhood of [Entity: Melanie] for connected nodes of type Person. By analyzing the semantic edges, specifically distinguishing the "two kids"

entity in the canyon photo from the "son" entity involved in the car accident, MAGMA synthesized these distinct nodes. It correctly deduced that the "son" (referenced later as "brother") was an addi- tional individual, summing up to a count of "at least three," a logical leap impossible for systems relying solely on vector similarity.

Case 3: Temporal Grounding. When asked "When did she hike?", baselines either halluci- nated or defaulted to the conversation timestamp (Oct 20). This ignores the semantic meaning of the user’s statement: "we just did it yester- day." MAGMA’s structured ingestion pipeline nor- malizes relative dates during graph construction. The event was stored with the resolved attribute date="2023-10-19", making the retrieval trivial and exact, completely bypassing the ambiguity that confused the LLM-based baselines.

## F Metric Validation Analysis

To validate our choice of using an LLM-based Judge over traditional lexical metrics, we con- ducted a granular failure analysis on seven repre- sentative test cases. Table 9 details the quantitative breakdown. [URL 🔗](#page-0)

## F.1 Rationale for Semantic Scoring

Our empirical results reveal two critical failure modes where standard metrics (F1, BLEU-1) di- rectly contradict human judgment:

- 1. False Rewards (The “Hallucination” Prob- lem): Lexical metrics heavily reward incorrect answers that share surface-level tokens.

- In Case 3, a direct negation (“compatible” vs. “not compatible”) yields a remark- ably high F1 of 0.857, treating a fatal contradiction as a near-perfect match.

- In Case 6, substituting the wrong entity (“John” vs. “Sarah”) still achieves F1 0.750, rewarding the hallucinatory out- put.

- 2. False Penalties (The “Phrasing” Problem): Valid answers with different formatting or syn- onyms are unfairly penalized.

- In Case 4 (Time Notation) and Case 5 (Synonyms), F1 and BLEU scores drop to 0.000 despite the answers being se- mantically identical.


*Table 7: Case study for failure analysis comparing MAGMA against baselines across three reasoning types. Red text indicates hallucinations or partial failures; Teal text indicates correct reasoning derived from graph traversal.*

|   | Query & Type | Baseline Failure Mode |   | MAGMA Graph Reasoning (Success) |
| --- | --- | --- | --- | --- |
| Fact | Q1: Fact Retrieval | A-MEM: | "Memories do not explicitly | "Clarinet and Violin." |
|   | "What instruments | state..." |   | Mechanism: MAGMA utilized the entity- |
|   | does Melanie play?" | MemoryOS: "Clarinet" |   | centric subgraph around "Melanie". By |
|   |   | Failure: | Baselines relying on top-k vector | traversing dynamic semantic edges (e.g., |
|   |   | search missed the distant memory of the "vi- |   | "playing", "enjoy") to connected event nodes, |
|   |   | olin" (D2:5) because it appeared in a context |   | it aggregated all mentions of musical activ- |
|   |   | about "me-time" rather than explicitly about |   | ities regardless of the specific relation label |
|   |   | music. |   | or distance. |
| Logic | Q2: Logical Infer- | Nemori: "At least two..." |   | "At least three." |
|   | ence | MemoryOS: "Two" |   | Mechanism: MAGMA executed multi-hop |
|   | "How many children |   | Failure: Baselines performed surface-level | inference focused on Entity Resolution: 1. |
|   | does Melanie have?" | extraction from a photo description showing |   | Node A (Photo): Identified "two kids" entity. |
|   |   | "two children" (D18:5), failing to account for |   | 2. Node B (Accident): Linked "son" (D18:1) |
|   |   | the "son" mentioned in a separate accident |   | via a dynamic relationship edge. 3. Node C |
|   |   | event. |   | (Dialogue): Confirmed "brother" (D18:7) is |
|   |   |   |   | distinct from the two in the photo. → Logic: |
|   |   |   |   | 2 (Photo) + 1 (Son/Brother) = 3. |
| Time | Q3: Temporal Res. | A-MEM: "20 October 2023" |   | "19 October 2023" |
|   | "When did she hike af- | MemoryOS: "29 December 2025" |   | Mechanism: MAGMA’s Temporal Parser |
|   | ter the roadtrip?" |   | Failure: A-MEM simply copied the session | identified the relative marker "yesterday" |
|   |   | timestamp. MemoryOS hallucinated a future |   | in D18:17. Calculation: Tsession(Oct20) − |
|   |   | date. Both failed to resolve the relative time |   | 1 day = Oct19. This exact date was an- |
|   |   | expression. |   | chored to the Event Node, allowing precise |
|   |   |   |   | retrieval. |

*Table 8: LoCoMo evaluation with F1 and BLEU-1 metrics*

| Multi-Hop | Temporal | Open-Domain | Single-Hop | Overall |
| --- | --- | --- | --- | --- |
| Method F1 BLEU-1 F1 BLEU-1 F1 BLEU-1 F1 BLEU-1 |   |   |   | F1 BLEU-1 |
| Full Context |   |   | 0.182 0.128 0.079 0.055 0.042 0.030 0.229 0.156 | 0.140 0.096 |
| A-MEM |   |   | 0.128 0.088 0.128 0.079 0.076 0.051 0.174 0.110 | 0.116 0.074 |
| MemoryOS |   |   | 0.365 0.276 0.434 0.369 0.246 0.191 0.493 0.437 | 0.413 0.355 |
| Nemori |   |   | 0.363 0.249 0.569 0.479 0.247 0.189 0.548 0.439 | 0.502 0.403 |
|   | MAGMA (ours) 0.264 0.172 0.509 0.370 0.180 0.136 0.551 0.477 |   |   | 0.467 0.378 |

As shown in Table 9, the LLM-Judge correctly assigns a score of 0.0 to factual errors and 1.0 to se- mantic matches, aligning perfectly with reasoning requirements. [URL 🔗](#page-0)


*Table 9: Quantitative Failure Analysis of Lexical Metrics. We present seven controlled cases with their calculated F1 and BLEU-1 scores. The data demonstrates that lexical metrics frequently assign high scores to fatal errors (False Rewards) and zero scores to correct variations (False Penalties), whereas the LLM-Judge correctly assesses semantic validity.*

| Failure Mode Case Detail (Gold / Predicted) Lexical Met- LLM Judge rics (Semantic) (F1 /BLEU-1) Case 1: False Reward Gold: “three items” High 0.0 (Wrong Fact, High Overlap) Pred: “five items” 0.500 / 0.500 (Reject) Analysis: Factually wrong count, but rewarded for sharing the noun “items”. Case 2: False Penalty Gold: “18 days” Low 1.0 (Verbose Phrasing) Pred: “The total duration was 18 days” 0.500 / 0.333 (Accept) Analysis: Correct answer penalized for low pre- cision due to extra words. Case 3: False Reward Gold: “compatible with Mac” Very High 0.0 (Negation/Contradiction) Pred: “not compatible with Mac” 0.857 / 0.750 (Reject) Analysis: Fatal contradiction receives near- perfect scores due to high token overlap. |
| --- |
| Case 4: False Penalty Gold: “14:00” Zero 1.0 (Time Notation) Pred: “2 PM” 0.000 / 0.000 (Accept) Analysis: Different formats result in zero over- lap despite identical meaning. Case 5: False Penalty Gold: “cheap” Zero 1.0 (Synonyms) Pred: “inexpensive” 0.000 / 0.000 (Accept) Analysis: Standard metrics cannot handle syn- onym matching without external resources. Case 6: False Reward Gold: “John completed the project” High 0.0 (Entity Hallucination) Pred: “Sarah completed the project” 0.750 / 0.750 (Reject) Analysis: Wrong entity (Sarah vs John), yet high metrics due to shared sentence structure. Case 7: False Penalty Gold: “5” Low 1.0 (Format Noise) Pred: “5 (extracted from JSON...)” 0.286 / 0.167 (Accept) Analysis: Correct value embedded in noise re- sults in poor precision metrics. |
