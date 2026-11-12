import { App as AntdApp, ConfigProvider, Empty } from 'antd';
import zhCN from './locale';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { AppRoutes } from './router/AppRoutes';
import { theme } from './theme';

dayjs.locale('zh-cn');

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={theme}
      renderEmpty={() => <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />}
    >
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>
  );
}
