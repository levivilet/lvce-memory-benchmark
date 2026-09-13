const editor = document.querySelector('#editor')
const save = document.querySelector('#save')
const status = document.querySelector('#status')

function showError(error) {
  status.textContent = `Error: ${error.message}`
  status.dataset.state = 'error'
}

async function saveFile() {
  save.disabled = true
  try {
    await window.basicElectronEditor.writeFile(editor.value)
    status.textContent = 'Saved'
    status.dataset.state = 'saved'
  } catch (error) {
    showError(error)
  } finally {
    save.disabled = false
  }
}

save.addEventListener('click', saveFile)
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    saveFile()
  }
})

window.basicElectronEditor.readFile().then((contents) => {
  editor.value = contents
  status.textContent = 'Loaded'
  status.dataset.state = 'loaded'
  editor.focus()
}).catch(showError)
