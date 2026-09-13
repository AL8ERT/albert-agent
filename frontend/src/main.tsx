/**
 * 前端入口：挂载根组件并引入全局样式。
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@/styles/global.css'
import App from './App.tsx'

// StrictMode 在开发模式下会双执行 effect，便于提前发现副作用问题
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
