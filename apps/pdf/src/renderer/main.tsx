import { createRoot } from 'react-dom/client'
import { htmlLang, type Lang } from '@trivoffice/i18n'
import App from './App'
import { LocaleProvider } from './i18n/locale'
import type { UiTheme } from '../shared/ipc'
import '@trivoffice/ui/tokens.css'
import '@trivoffice/ui/screentip.css'
import './styles.css'
import { installScreenTips } from '@trivoffice/ui'

installScreenTips()

function applyTheme(theme: UiTheme): void {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', theme)
}

void (async () => {
  const [lang, theme] = await Promise.all([
    window.pdfApi.getLanguage().catch(() => 'zh' as const),
    window.pdfApi.getTheme().catch(() => 'system' as const),
  ])
  document.documentElement.lang = htmlLang(lang as Lang)
  applyTheme(theme)
  window.pdfApi.onThemeChanged(applyTheme)
  createRoot(document.getElementById('root')!).render(
    <LocaleProvider initial={lang}>
      <App />
    </LocaleProvider>,
  )
})()
