import type { ThemeConfig } from 'antd';

/** 视觉方案见 docs/features/20261111-knowledge-base-platform/ui-design.md */
export const COLORS = {
  ink: '#1E2A32',
  primary: '#0E6E6E',
  paper: '#F5F7F6',
  frost: '#E2E7E4',
  /** 藤黄：只用于检索命中高亮 */
  hit: '#F2C14E',
} as const;

export const FONT_SANS =
  '"PingFang SC", "HarmonyOS Sans SC", "MiSans", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif';
export const FONT_SERIF = '"Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", serif';

export const theme: ThemeConfig = {
  token: {
    colorPrimary: COLORS.primary,
    colorInfo: COLORS.primary,
    colorLink: COLORS.primary,
    colorTextBase: COLORS.ink,
    colorBgLayout: COLORS.paper,
    colorBorder: '#D3DAD6',
    colorBorderSecondary: COLORS.frost,
    colorSplit: COLORS.frost,
    fontFamily: FONT_SANS,
    fontSize: 14,
    lineHeight: 1.6,
    borderRadius: 6,
  },
  components: {
    Layout: { headerBg: COLORS.ink, bodyBg: COLORS.paper },
    Table: { headerBg: '#EEF2F0', borderColor: COLORS.frost },
    Card: { colorBorderSecondary: COLORS.frost },
    Menu: {
      itemSelectedBg: 'rgba(14, 110, 110, 0.08)',
      itemSelectedColor: COLORS.primary,
    },
  },
};
