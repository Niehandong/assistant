import type { ReactNode } from 'react';
import BrandMark from '@/components/BrandMark';
import styles from './AuthShell.module.css';

/** 登录/改密页共用外壳：左侧墨色品牌面板，右侧表单区；窄屏上下堆叠 */
export default function AuthShell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className={styles.root}>
      <section className={styles.brand}>
        <BrandMark size={72} />
        <h1 className={styles.title}>知识库平台</h1>
        <p className={styles.desc}>把制度、手册和表格整理成可以检索的知识库。</p>
      </section>
      <main className={styles.panel}>
        <div className={styles.formBox}>
          {title && <h2 className={styles.formTitle}>{title}</h2>}
          {children}
        </div>
      </main>
    </div>
  );
}
