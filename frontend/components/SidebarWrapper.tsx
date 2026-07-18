'use client'

import Sidebar from './Sidebar'
import { useTheme } from './ThemeProvider'

export default function SidebarWrapper() {
  const { theme, toggle } = useTheme()
  return <Sidebar onThemeToggle={toggle} isDark={theme === 'dark'} />
}
