import {
  ApartmentOutlined,
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  HistoryOutlined,
  KeyOutlined,
  LoginOutlined,
  ProfileOutlined,
  ReadOutlined,
  SafetyOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ComponentType, ReactNode } from 'react';

/** 后端菜单 icon 名 -> 图标组件；未收录的名称不显示图标 */
export const MENU_ICON_NAMES = [
  'ApartmentOutlined',
  'ApiOutlined',
  'AppstoreOutlined',
  'AuditOutlined',
  'CloudServerOutlined',
  'DatabaseOutlined',
  'FileSearchOutlined',
  'FileTextOutlined',
  'HistoryOutlined',
  'KeyOutlined',
  'LoginOutlined',
  'ProfileOutlined',
  'ReadOutlined',
  'SafetyOutlined',
  'SettingOutlined',
  'TeamOutlined',
  'UserOutlined',
] as const;

const ICONS: Record<string, ComponentType> = {
  ApartmentOutlined,
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  HistoryOutlined,
  KeyOutlined,
  LoginOutlined,
  ProfileOutlined,
  ReadOutlined,
  SafetyOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
};

export function renderMenuIcon(name: string | null | undefined): ReactNode {
  const Icon = name ? ICONS[name] : undefined;
  return Icon ? <Icon /> : null;
}
