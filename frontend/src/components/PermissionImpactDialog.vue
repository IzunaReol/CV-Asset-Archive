<script setup lang="ts">
defineProps<{
  impact: any
  busy: boolean
  menuName: (key: string) => string
  actionName: (key: string) => string
}>()
defineEmits<{ cancel: []; confirm: [] }>()
</script>

<template>
  <div class="modal-stage permission-impact-stage">
    <section class="upload-dialog permission-impact-dialog">
      <button class="close" :disabled="busy" @click="$emit('cancel')">×</button>
      <header><small>权限影响预览</small><h2>确认更新角色权限</h2><p>保存后，绑定该角色的用户将立即按照新权限访问系统。</p></header>
      <div class="permission-impact-summary"><article><b>{{impact?.affected_count||0}}</b><span>受影响用户</span></article><article><b>{{impact?.active_count||0}}</b><span>正常账号</span></article><article><b>{{impact?.disabled_count||0}}</b><span>停用账号</span></article></div>
      <section class="permission-impact-changes">
        <article class="granted"><h3>新增权限</h3><div><span v-for="key in impact?.menus_added||[]" :key="`ma-${key}`">菜单 · {{menuName(key)}}</span><span v-for="key in impact?.actions_added||[]" :key="`aa-${key}`">操作 · {{actionName(key)}}</span><small v-if="!(impact?.menus_added?.length||impact?.actions_added?.length)">无新增权限</small></div></article>
        <article class="revoked"><h3>移除权限</h3><div><span v-for="key in impact?.menus_removed||[]" :key="`mr-${key}`">菜单 · {{menuName(key)}}</span><span v-for="key in impact?.actions_removed||[]" :key="`ar-${key}`">操作 · {{actionName(key)}}</span><small v-if="!(impact?.menus_removed?.length||impact?.actions_removed?.length)">无移除权限</small></div></article>
      </section>
      <section class="permission-impact-users"><h3>受影响用户</h3><div><span v-for="item in impact?.users||[]" :key="item.username"><b>{{item.username}}</b><small>{{item.status==='disabled'?'已停用':'正常'}}</small></span></div><p v-if="impact?.users_truncated">仅展示前 {{impact?.users?.length||0}} 个用户</p></section>
      <div v-if="impact?.menus_removed?.length||impact?.actions_removed?.length" class="permission-impact-warning">请确认被移除权限的用户不再需要对应菜单或操作。</div>
      <div class="dialog-actions"><button class="secondary" :disabled="busy" @click="$emit('cancel')">返回调整</button><button class="primary" :disabled="busy" @click="$emit('confirm')">{{busy?'正在保存…':'确认并保存'}}</button></div>
    </section>
  </div>
</template>
