import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Sources from '../views/Sources.vue'
import Channels from '../views/Channels.vue'
import Settings from '../views/Settings.vue'

const routes = [
  { path: '/', name: 'Home', component: Home, meta: { title: '首页' } },
  { path: '/sources', name: 'Sources', component: Sources, meta: { title: '订阅源' } },
  { path: '/channels', name: 'Channels', component: Channels, meta: { title: '频道管理' } },
  { path: '/settings', name: 'Settings', component: Settings, meta: { title: '设置' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const title = to.meta.title as string
  document.title = `iptv-manager｜${title}`
  next()
})

export default router
