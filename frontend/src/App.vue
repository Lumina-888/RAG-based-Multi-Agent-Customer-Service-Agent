<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand">智能客服多Agent系统</div>
      <el-menu mode="horizontal" :router="true" :default-active="$route.path" class="nav">
        <el-menu-item index="/">对话</el-menu-item>
        <el-menu-item index="/eval">评测看板</el-menu-item>
        <el-menu-item index="/tickets">工单管理</el-menu-item>
      </el-menu>
    </el-header>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
// 顶层壳：导航 + 路由出口（SP-FE-001~003 三页共用）
</script>
