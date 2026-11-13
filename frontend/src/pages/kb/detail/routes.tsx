import { Route, Routes } from 'react-router-dom';
import PlaceholderPage from '@/pages/placeholder';
import AssignmentsPage from './assignments';
import DocumentsPage from './documents';
import DatasetLayout from './Layout';
import RecallPage from './recall';
import SegmentsPage from './segments';
import SettingsPage from './settings';
import UploadPage from './upload';

/**
 * 知识库详情子路由（挂在 /kb/datasets/:id/* 下）。
 * 权限码校验在外层 RequirePerm（kb:dataset:list），页内按钮再按权限码/ACL 控制。
 */
export default function DatasetDetailRoutes() {
  return (
    <Routes>
      <Route element={<DatasetLayout />}>
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/upload" element={<UploadPage />} />
        <Route path="documents/:documentId/segments" element={<SegmentsPage />} />
        <Route path="recall" element={<RecallPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="assignments" element={<AssignmentsPage />} />
        <Route path="*" element={<PlaceholderPage title="页面不存在" />} />
      </Route>
    </Routes>
  );
}
