// 必须从 ESM 入口引入：`antd/locale/zh_CN` 是 CJS，经 Vite 预构建后会被包成 { default: {...} }，
// 导致 ConfigProvider 拿不到 locale（modal.confirm 取消按钮显示 Cancel）。
import zhCN from 'antd/es/locale/zh_CN';

export default zhCN;
