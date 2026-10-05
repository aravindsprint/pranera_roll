import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '@/api/frappe'

// ── Eager (statically bundled) — reachable even when the network drops ──
import LoginPage       from '@/pages/login/LoginPage.vue'
import CreateRollsPage from '@/pages/create-rolls/CreateRollsPage.vue'
import RollsPage       from '@/pages/rolls/RollsPage.vue'

const HOME = '/roll-app/my-pick-orders'

const routes = [
  { path: '/',         redirect: HOME },
  { path: '/roll-app', redirect: HOME },

  { path: '/roll-app/login', component: LoginPage },

  // Side-menu pages
  { path: '/roll-app/my-pick-orders', component: () => import('@/pages/my-pick-orders/MyPickOrdersPage.vue') },
  { path: '/roll-app/create-rolls',   component: CreateRollsPage },
  { path: '/roll-app/rolls',          component: RollsPage },

  { path: '/roll-app/verify-rolls',   component: () => import('@/pages/verify-rolls/VerifyRollsPage.vue') },

  // Opened from a row on My Pick Orders (not in the menu itself)
  { path: '/roll-app/roll-wise-pick-order-execution', component: () => import('@/pages/roll-wise-pick-order-execution/RollWisePickOrderExecutionPage.vue') },

  // Anything else (old bookmarks, typos) → landing page
  { path: '/roll-app/:pathMatch(.*)*', redirect: HOME },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const loggedIn = isLoggedIn()
  if (to.path !== '/roll-app/login' && !loggedIn) {
    return { path: '/roll-app/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/roll-app/login' && loggedIn) {
    return { path: HOME }
  }
  return true
})

export default router
