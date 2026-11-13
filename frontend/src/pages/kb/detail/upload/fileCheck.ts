/** 上传预检与并发队列（FE-12，PRD F-11 规则 1~3、AC-36） */

export const ALLOWED_EXTS = [
  'txt',
  'md',
  'markdown',
  'pdf',
  'docx',
  'xlsx',
  'xls',
  'csv',
  'html',
  'htm',
  'pptx',
] as const;
export const MAX_FILE_BYTES = 15 * 1024 * 1024;
export const MAX_FILES = 20;
export const UPLOAD_CONCURRENCY = 3;

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i + 1).toLowerCase();
}

/** 前端预检：返回错误原因，通过返回 null（与后端 400501/400502/400503 文案一致） */
export function precheckFile(file: { name: string; size: number }): string | null {
  if (!(ALLOWED_EXTS as readonly string[]).includes(fileExt(file.name))) {
    return '不支持的文件类型';
  }
  if (file.size === 0) return '文件为空';
  if (file.size > MAX_FILE_BYTES) return '文件超过 15 MB';
  return null;
}

/** 本次可加入的文件数：超过总上限的部分被丢弃，返回 [接收, 丢弃数] */
export function limitFiles<T>(existingCount: number, incoming: T[]): [T[], number] {
  const room = Math.max(0, MAX_FILES - existingCount);
  return [incoming.slice(0, room), Math.max(0, incoming.length - room)];
}

/** 按并发上限依次执行任务；任务自身负责捕获错误（不应抛出） */
export async function runWithConcurrency<T>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  let next = 0;
  const lanes = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const item = items[next++];
      await worker(item);
    }
  });
  await Promise.all(lanes);
}

export type UploadItemStatus = 'invalid' | 'queued' | 'uploading' | 'done' | 'error';

export interface UploadItem {
  uid: string;
  file: File;
  status: UploadItemStatus;
  progress: number;
  error?: string;
  uploadFileId?: number;
}

let seq = 0;
/** 把选中的文件转为上传条目：预检失败直接标 invalid（红色，不上传） */
export function toUploadItems(files: File[]): UploadItem[] {
  return files.map((file) => {
    const reason = precheckFile(file);
    seq += 1;
    return {
      uid: `${Date.now()}-${seq}`,
      file,
      status: reason ? 'invalid' : 'queued',
      progress: 0,
      error: reason ?? undefined,
    };
  });
}

/** 后端错误 -> 逐文件展示文案；重复内容带上已有文档名（AC-38） */
export function uploadErrorMessage(err: unknown): string {
  const e = err as { code?: number; message?: string; data?: unknown } | null;
  if (e?.code === 409501) {
    const name = (e.data as { existing_document_name?: string } | null)?.existing_document_name;
    if (name) return `与已有文档《${name}》内容重复`;
  }
  return e?.message || '上传失败';
}

/** 已上传成功、可进入下一步/提交的条目 */
export const doneItems = (items: UploadItem[]) => items.filter((i) => i.status === 'done');
export const isBusy = (items: UploadItem[]) =>
  items.some((i) => i.status === 'queued' || i.status === 'uploading');
