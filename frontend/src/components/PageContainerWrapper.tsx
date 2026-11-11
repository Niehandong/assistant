import { PageContainer } from '@ant-design/pro-components';
import { Button, Empty, Result, Skeleton } from 'antd';
import type { ReactNode } from 'react';

interface Props {
  title?: string;
  loading?: boolean;
  /** 有值时显示错误态 */
  error?: Error | null;
  onRetry?: () => void;
  empty?: boolean;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
}

/** 页面容器：统一处理加载中、错误（带重试）、空数据三种状态 */
export default function PageContainerWrapper({
  title,
  loading,
  error,
  onRetry,
  empty,
  emptyDescription = '暂无数据',
  emptyAction,
  extra,
  children,
}: Props) {
  let body: ReactNode = children;
  if (loading) {
    body = <Skeleton active paragraph={{ rows: 8 }} />;
  } else if (error) {
    body = (
      <Result
        status="error"
        title="加载失败"
        subTitle={error.message}
        extra={onRetry && <Button onClick={onRetry}>重试</Button>}
      />
    );
  } else if (empty) {
    body = <Empty description={emptyDescription}>{emptyAction}</Empty>;
  }
  return (
    <PageContainer title={title} extra={extra}>
      {body}
    </PageContainer>
  );
}
