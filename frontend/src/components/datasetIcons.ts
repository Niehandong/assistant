import {
  BookOutlined,
  BulbOutlined,
  CloudOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FolderOutlined,
  ProfileOutlined,
  ReadOutlined,
  RocketOutlined,
  SafetyOutlined,
  ShopOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import type { ComponentType, CSSProperties } from 'react';

/** 知识库预置图标库：key 存库（≤50 字符），未知 key 回退为默认图标 */
export const DATASET_ICONS: Record<string, ComponentType<{ style?: CSSProperties }>> = {
  book: BookOutlined,
  read: ReadOutlined,
  database: DatabaseOutlined,
  file: FileTextOutlined,
  folder: FolderOutlined,
  cloud: CloudOutlined,
  bulb: BulbOutlined,
  profile: ProfileOutlined,
  shop: ShopOutlined,
  team: TeamOutlined,
  safety: SafetyOutlined,
  rocket: RocketOutlined,
};

export const DEFAULT_DATASET_ICON = 'book';
