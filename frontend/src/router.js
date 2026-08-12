import { createRouter, createWebHistory } from 'vue-router'
import ChatView from './views/ChatView.vue'
import EvalBoard from './views/EvalBoard.vue'
import Tickets from './views/Tickets.vue'

// 路由（设计文档 §8.2）：/ 对话页、/eval 评测看板、/tickets 工单管理；
// 追踪面板作为对话页右侧抽屉（同一视图内联动）
export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/eval', name: 'eval', component: EvalBoard },
    { path: '/tickets', name: 'tickets', component: Tickets },
  ],
})
