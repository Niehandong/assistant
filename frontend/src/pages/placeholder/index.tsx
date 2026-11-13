import { Empty } from 'antd';

/** 尚未实现的页面占位（后续任务替换） */
export default function PlaceholderPage({ title }: { title: string }) {
  return <Empty style={{ padding: 64 }} description={`${title}（建设中）`} />;
}
