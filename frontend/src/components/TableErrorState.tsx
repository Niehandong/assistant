import { Button, Result } from 'antd';

/** ProTable 加载失败占位（放入 locale.emptyText） */
export default function TableErrorState({
  message,
  onRetry,
}: {
  message?: string;
  onRetry: () => void;
}) {
  return (
    <Result
      status="error"
      title="加载失败"
      subTitle={message}
      extra={
        <Button type="primary" onClick={onRetry}>
          重试
        </Button>
      }
    />
  );
}
