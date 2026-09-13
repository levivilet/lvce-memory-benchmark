const {contextBridge, ipcRenderer} = require('electron')

contextBridge.exposeInMainWorld('basicElectronEditor', {
  readFile: () => ipcRenderer.invoke('read-file'),
  writeFile: (contents) => ipcRenderer.invoke('write-file', contents),
})
