import { app, BrowserWindow } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import * as path from 'path'

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcess | null = null

const isDev = !app.isPackaged

function startBackend(): void {
  const backendPath = path.join(__dirname, '..', 'backend')
  backendProcess = spawn('python', ['-m', 'uvicorn', 'backend.main:app', '--port', '8765'], {
    cwd: path.join(__dirname, '..'),
    stdio: 'pipe',
  })

  backendProcess.stdout?.on('data', (data: Buffer) => {
    console.log(`[backend] ${data.toString().trim()}`)
  })

  backendProcess.stderr?.on('data', (data: Buffer) => {
    console.error(`[backend] ${data.toString().trim()}`)
  })

  backendProcess.on('exit', (code: number | null) => {
    console.log(`Backend exited with code ${code}`)
  })
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    title: 'Mayday',
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(() => {
  startBackend()
  // Give backend a moment to start
  setTimeout(createWindow, 2000)
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow()
  }
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
})
