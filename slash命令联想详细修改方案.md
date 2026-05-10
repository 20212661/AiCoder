# aicoder-tui Slash 命令联想详细修改方案

## 目标

在 `aicoder-tui` 中实现类似 Claude Code 的 `/` 命令联想体验，并为后续 skill 接入预留统一入口。

第一期目标：

1. 输入 `/` 时显示全部可用命令
2. 输入 `/mo` 时过滤出 `/model`
3. 支持 `↑` `↓` 选择
4. 支持 `Tab` 补全
5. 支持 `Enter`
   - 有候选时优先补全
   - 没候选时正常提交
6. 支持 `Esc` 关闭菜单

第一期暂不包含：

- 模糊搜索
- 分组展示
- 描述换行
- 最近使用排序
- 鼠标操作
- skill 真实执行逻辑

---

## 总体设计

数据流如下：

1. Python 后端生成命令列表
2. `rpc_io.py` 通过 `input/request` 发给前端
3. TUI 的 `useBackend.ts` 接收并写入 store
4. `InputBar.tsx` 读取 store 中的命令列表
5. `InputBar.tsx` 根据当前输入内容计算候选项
6. `SlashCommandMenu.tsx` 渲染候选列表
7. 选中某项后，把输入框内容补全成命令文本

---

## 需要修改的文件与职责

### 1. `aicoder/rpc_io.py`

职责：把后端命令列表真正发给前端。

当前问题：

在 `serve()` 中调用 `get_input(...)` 时，传的是空命令数组 `[]`，导致前端拿不到候选命令源。

建议修改：

- 在 `serve()` 中先获取当前命令列表：
  - `commands = coder.commands.get_commands() if coder.commands else []`
- 把 `commands` 传入 `get_input(...)` 的 `commands` 参数

当前调用语义应从：

- `coder.root`
- `coder.get_inchat_relative_files()`
- `coder.get_addable_relative_files()`
- `[]`
- `[]`

改为：

- `coder.root`
- `coder.get_inchat_relative_files()`
- `coder.get_addable_relative_files()`
- `commands`
- `[]`

预期效果：

前端收到的 `input/request` 会真正包含：

- `root`
- `inchat_files`
- `addable_files`
- `commands`

---

### 2. `aicoder-tui/src/rpc/protocol.ts`

职责：补全 `input/request` 协议定义。

当前问题：

`input/request` 当前仅定义为：

- `{ root: string }`

而后端实际发送的数据更多。

建议修改：

把 `input/request` 的类型扩展为至少包含：

- `root: string`
- `commands?: string[]`
- `inchat_files?: string[]`
- `addable_files?: string[]`

原因：

第一期真正用到的是 `commands`，但把其他字段一起补齐后，后续若要做文件候选、上下文提示，就不用再改协议层。

---

### 3. `aicoder-tui/src/stores/configStore.ts`

职责：保存后端下发的命令列表。

当前问题：

`configStore` 当前只保存：

- `model`
- `theme`
- `showSidebar`
- `showThinking`
- `planMode`
- `yolo`

没有输入联想相关状态。

建议新增字段：

在 `AppConfig` 中增加：

- `commands: string[]`
- `workspaceRoot?: string`

在 `ConfigState` 中增加：

- `setCommands: (commands: string[]) => void`
- `setWorkspaceRoot: (root: string) => void`

建议：

第一期直接继续使用 `configStore`，不要新建额外 store，先减少改动面。

原因：

命令列表属于前端全局上下文，不属于聊天消息，因此不应塞进 `chatStore`。

---

### 4. `aicoder-tui/src/hooks/useBackend.ts`

职责：监听后端 `input/request`，把命令列表写入前端状态。

当前问题：

这个文件监听了：

- `stream/token`
- `stream/finalize`
- `tool/call_started`
- `tool/call_finished`
- `approval/request`
- `status/update`
- `ready`

但没有监听 `input/request`。

建议新增监听：

- `rpc.on("input/request", ...)`

收到通知后执行：

1. 如果 `params.commands` 是数组，则写入 `configStore`
2. 如果 `params.root` 是字符串，则写入 `configStore`

职责边界：

- `useBackend.ts` 只负责同步后端数据
- 不在这里做过滤、排序或 UI 判断
- 输入逻辑全部留给 `InputBar.tsx`

---

### 5. `aicoder-tui/src/components/chat/InputBar.tsx`

职责：实现 slash 输入检测、候选过滤、键盘交互、补全。

这是第一期改动最多的文件。

#### 5.1 新增本地状态

建议新增：

- `selectedIndex`
- `showMenu`

建议从 store 读取：

- `commands`

建议在组件内部维护派生值：

- `isSlashMode`
- `commandPrefix`
- `filteredCommands`

---

#### 5.2 新增辅助函数

建议在组件内部新增以下小函数。

##### `getCommandPrefix(input: string): string | null`

职责：

- 如果输入不以 `/` 开头，返回 `null`
- 如果是 `/model abc`，返回 `/model`
- 如果是 `/mo`，返回 `/mo`

规则：

- 只分析第一个空格前的 token
- 第一版不处理引号和转义

##### `filterCommands(prefix: string, commands: string[]): string[]`

职责：

- 用前缀匹配候选命令
- 如果 prefix 是 `/`，返回全部命令
- 过滤规则为 `cmd.startsWith(prefix)`

第一期不做模糊匹配。

##### `applySelectedCommand(selectedCommand: string, currentInput: string): string`

职责：

- 用完整命令替换当前输入中的 slash 前缀
- 补全后建议自动追加一个空格

示例：

- `/mo` -> `/model `
- `/model` -> `/model `

---

#### 5.3 输入状态判断

每次渲染时，根据当前 `input` 计算：

##### `isSlashMode`

条件建议：

- `input.startsWith("/")`

##### `prefix`

调用 `getCommandPrefix(input)`

##### `filteredCommands`

调用 `filterCommands(prefix, commands)`

##### `showMenu`

建议 `showMenu` 既受输入状态控制，也保留 state 能力。

原因：

- 如果完全依赖派生值，按 `Esc` 关闭菜单后，下次 render 还会自动出现
- 使用 state 后，`Esc` 才能真正关闭菜单

---

#### 5.4 使用 `useEffect` 处理输入变化

建议添加一个 `useEffect`，监听：

- `input`
- `commands`

逻辑：

1. 如果不是 slash 模式：
   - `showMenu = false`
   - `selectedIndex = 0`

2. 如果是 slash 模式且存在候选：
   - `showMenu = true`
   - 如果 `selectedIndex` 越界，则重置为 0

3. 如果是 slash 模式但无候选：
   - 第一版建议隐藏菜单
   - 不显示空态

---

#### 5.5 键盘处理逻辑

当前 `useInput(...)` 仅处理：

- 回车
- 退格
- 普通字符输入

需要增强以下键位。

##### `upArrow`

条件：

- `showMenu === true`
- `filteredCommands.length > 0`

逻辑：

- `selectedIndex = (selectedIndex - 1 + filteredCommands.length) % filteredCommands.length`

##### `downArrow`

条件：

- `showMenu === true`
- `filteredCommands.length > 0`

逻辑：

- `selectedIndex = (selectedIndex + 1) % filteredCommands.length`

##### `tab`

条件：

- `showMenu === true`
- 存在当前选中项

逻辑：

1. 用当前候选补全输入框
2. 补全后关闭菜单
3. 不提交到后端

##### `escape`

条件：

- 非 streaming 状态
- `showMenu === true`

逻辑：

1. 关闭菜单
2. 不清空输入框

注意：

`Esc` 目前在更上层 [App.tsx] 中已被用来取消流式生成，因此这里只处理非 streaming 场景下的菜单关闭。

##### `return`

逻辑分支：

1. 如果 `showMenu === true` 且存在候选项：
   - 优先补全当前选中项
   - 不提交消息

2. 否则：
   - 走现有回车提交逻辑

这是实现 Claude Code 类似体验的关键，否则一按回车会直接把 `/mo` 发给后端。

---

#### 5.6 渲染结构调整

当前结构大致为：

- 上分割线
- 输入行
- 下分割线

建议调整为：

- 上分割线
- 候选菜单
- 输入行
- 下分割线

原因：

这样候选菜单位于输入框上方，视觉和使用习惯更接近 Claude Code。

---

### 6. 新增 `aicoder-tui/src/components/chat/SlashCommandMenu.tsx`

职责：专门渲染候选命令列表。

建议新增这个组件，避免把所有渲染逻辑塞进 `InputBar.tsx`。

建议 Props：

- `commands: string[]`
- `selectedIndex: number`
- `visible: boolean`

最小渲染规则：

- `visible === false` 时返回 `null`
- 一行显示一个命令
- 当前选中项高亮
- 其他项普通显示或 `dim`

第一版展示内容：

- 仅显示命令名

示例：

- `/model`
- `/help`
- `/plan`
- `/act`

第一期不显示描述，原因是后端当前只提供命令名，不提供结构化说明。

---

## 可选增强：命令描述支持

如果希望更接近 Claude Code，下一步增强点应是“命令说明文字”。

当前问题：

`Commands.get_commands()` 在 `aicoder/commands.py` 中只返回 `string[]`，没有描述。

但后端实际可以从 `cmd_xxx` 的 docstring 提取说明。

建议增强方向：

后端提供结构化命令元数据，例如：

```python
[
  {"name": "/model", "description": "切换 LLM 模型"},
  {"name": "/plan", "description": "切换到只读规划模式"},
]
```

如果走这条路，需要继续改：

- `aicoder/commands.py`
- `aicoder/rpc_io.py`
- `aicoder-tui/src/rpc/protocol.ts`
- `aicoder-tui/src/components/chat/SlashCommandMenu.tsx`

但这不属于第一期最小闭环，可放到第二步。

---

## 第二期：把 skill 接入同一个菜单

目标：

实现“输入 `/` 时，不仅匹配命令，也匹配 skill”。

这时前端候选数据结构不应再是 `string[]`，而应统一升级为对象结构：

```ts
type SlashItem = {
  type: "command" | "skill";
  name: string;
  description?: string;
  source?: string;
};
```

---

### 7. 第二期后端改造建议

当前 `aicoder` 仓库并没有成熟的 skill 运行时，因此第二期第一步不要急着做“执行系统”，而应先做“候选元数据源”。

可以考虑的 skill 来源：

1. 本地配置中的 skill 定义
2. 插件注册表中的扩展项
3. 后续再加入本地目录扫描

建议新增独立模块：

- `aicoder/skills_catalog.py`

职责：

- 返回 skill 列表
- 每个 skill 带 `name` 和 `description`

不建议一开始把这块塞进 `commands.py`，否则职责会混乱。

---

### 8. 第二期协议扩展

当前第一期是传：

- `commands`

第二期建议统一升级为：

- `slash_items`

即不再区分纯命令字符串，而是统一为对象数组。

可选兼容方案：

- 保留 `commands`
- 新增 `skills`

但更推荐一步到位改成：

- `slash_items`

这样前端候选菜单逻辑只写一套。

---

### 9. 第二期前端 store 设计

到第二期后，`configStore` 不应继续只存：

- `commands: string[]`

而应升级为：

- `slashItems: SlashItem[]`

之后 `InputBar.tsx` 和 `SlashCommandMenu.tsx` 都统一消费 `slashItems`。

---

### 10. 第二期前端菜单逻辑

`SlashCommandMenu.tsx` 需要增强为：

- 按 `type` 分组展示
- 命令项显示 `/model`
- skill 项显示 `/pptx` 或 `/skill:pptx`
- 右侧显示 `description`

这里需要做一个产品决策。

#### 方案 A：skill 也表现为 slash 命令

例如：

- `/pptx`
- `/docx`
- `/update-config`

优点：

- 使用体验更统一
- 更接近 Claude Code

缺点：

- 后端最终需要真正接住这些 skill 命令

#### 方案 B：skill 只是候选项，选中后插入提示模板

例如选中 `/pptx` 后，输入框自动变成：

- `请使用 pptx skill 处理这个文件：`

优点：

- 后端不必立刻改命令执行系统

缺点：

- 它不是真正的 slash 命令体验

建议：

如果追求 Claude Code 风格，应优先选择方案 A。

---

## 一期最小实现的函数级清单

### 后端

`aicoder/rpc_io.py`

- 修改 `serve()`
- 把 `coder.commands.get_commands()` 传入 `get_input(...)`

### 前端协议

`aicoder-tui/src/rpc/protocol.ts`

- 扩展 `BackendNotifications["input/request"]`

### 前端状态

`aicoder-tui/src/stores/configStore.ts`

- 新增 `commands`
- 新增 `workspaceRoot`
- 新增 setter

### 后端桥接

`aicoder-tui/src/hooks/useBackend.ts`

- 监听 `input/request`
- 将 `commands/root` 写入 store

### 输入组件

`aicoder-tui/src/components/chat/InputBar.tsx`

- 新增本地状态 `selectedIndex`
- 新增本地状态 `showMenu`
- 新增辅助函数 `getCommandPrefix`
- 新增辅助函数 `filterCommands`
- 新增补全逻辑
- 增强回车、Tab、上下键、Esc 逻辑
- 渲染菜单组件

### 菜单组件

`aicoder-tui/src/components/chat/SlashCommandMenu.tsx`

- 新建
- 负责渲染候选项和选中高亮

---

## 推荐实施顺序

1. 先改后端 `rpc_io.py`，保证命令真的发出来
2. 再改 `protocol.ts` 和 `useBackend.ts`，保证前端真的收到了
3. 再改 `configStore.ts`，保证前端状态存下来了
4. 最后改 `InputBar.tsx` 和新增 `SlashCommandMenu.tsx`
5. 等命令联想跑通后，再开始做 skill 接入

---

## 最终效果预期

第一阶段完成后，TUI 体验会从当前的：

- 只能手动输入 `/model`

升级为：

- 输入 `/`
- 自动弹出命令列表
- 输入 `/mo`
- 自动过滤为 `/model`
- 支持上下选择
- 支持 `Tab` 补全
- 支持 `Enter` 确认

这就是接近 Claude Code 的最小 slash 命令联想闭环。

第二阶段完成后，再把 skill 并入同一个候选菜单体系。
