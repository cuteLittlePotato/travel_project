/**
 * 景点图片编辑器。
 *
 * 对应后端 `attraction.image_urls`（JSONB 字符串数组，最多 10 张）。
 * 列表接口取**第一张**作为封面（`cover_image_url`），
 * 所以第一张的排序有实际意义——用「上移」按钮调整。
 *
 * **关于上传方式**：当前只支持填 URL，不支持本地上传。
 * 文件上传需要 MinIO 预签名接口（M09 知识库尚未实现该能力），
 * 现阶段运营可以先把图片放到图床/CDN，再填地址。
 * 加本地上传是后续独立任务，不在本功能范围内硬塞。
 */
import { useState } from 'react';
import { App, Button, Image, Input, Space, Tag, Typography } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';

/** 与后端 `image_urls` 的 max_length 保持一致 */
const MAX_IMAGES = 10;

/** 校验：必须是 http(s) 地址 */
const URL_PATTERN = /^https?:\/\/.+/;

export interface ImageUrlsFieldProps {
  value?: string[] | null;
  onChange?: (value: string[] | null) => void;
}

export function ImageUrlsField({ value, onChange }: ImageUrlsFieldProps) {
  const { message } = App.useApp();
  const images = value ?? [];
  const [draft, setDraft] = useState('');

  const emit = (next: string[]) => {
    onChange?.(next.length > 0 ? next : null);
  };

  const handleAdd = () => {
    const url = draft.trim();

    if (!url) {
      message.warning('请输入图片地址');
      return;
    }
    if (!URL_PATTERN.test(url)) {
      message.warning('图片地址必须以 http:// 或 https:// 开头');
      return;
    }
    if (images.includes(url)) {
      message.warning('该图片已添加');
      return;
    }
    if (images.length >= MAX_IMAGES) {
      message.warning(`最多添加 ${MAX_IMAGES} 张图片`);
      return;
    }

    emit([...images, url]);
    setDraft('');
  };

  const handleRemove = (index: number) => {
    emit(images.filter((_, i) => i !== index));
  };

  const handleMove = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= images.length) return;

    const next = [...images];
    const current = next[index];
    const other = next[target];
    if (current === undefined || other === undefined) return;
    next[index] = other;
    next[target] = current;
    emit(next);
  };

  return (
    <div>
      <Space.Compact style={{ width: '100%' }}>
        <Input
          placeholder="https://example.com/image.jpg"
          value={draft}
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          onPressEnter={handleAdd}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
          添加
        </Button>
      </Space.Compact>

      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        最多 {MAX_IMAGES} 张，第一张作为封面；未上传前可先填入图床地址
      </Typography.Text>

      {images.length === 0 ? (
        <div
          style={{
            marginTop: 8,
            padding: '16px 0',
            textAlign: 'center',
            color: '#bfbfbf',
            border: '1px dashed #d9d9d9',
            borderRadius: 6,
            fontSize: 13,
          }}
        >
          暂无图片
        </div>
      ) : (
        <div
          style={{
            marginTop: 8,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
            gap: 8,
          }}
        >
          {images.map((url, index) => (
            <div
              key={`${url}-${index}`}
              style={{
                border: '1px solid #f0f0f0',
                borderRadius: 6,
                overflow: 'hidden',
                position: 'relative',
              }}
            >
              <Image
                src={url}
                alt={`景点图片 ${index + 1}`}
                height={90}
                width="100%"
                style={{ objectFit: 'cover', display: 'block' }}
                fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMjAiIGhlaWdodD0iOTAiPjxyZWN0IHdpZHRoPSIxMjAiIGhlaWdodD0iOTAiIGZpbGw9IiNmNWY1ZjUiLz48dGV4dCB4PSI2MCIgeT0iNDgiIGZvbnQtc2l6ZT0iMTIiIGZpbGw9IiNiZmJmYmYiIHRleHQtYW5jaG9yPSJtaWRkbGUiPuaXoOazleWKoOi9veWbvueJhzwvdGV4dD48L3N2Zz4="
              />

              {index === 0 && (
                <Tag
                  color="blue"
                  style={{ position: 'absolute', top: 4, left: 4, margin: 0 }}
                >
                  封面
                </Tag>
              )}

              <Space
                size={0}
                style={{
                  display: 'flex',
                  justifyContent: 'center',
                  padding: '2px 0',
                  background: '#fafafa',
                }}
              >
                <Button
                  type="text"
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={index === 0}
                  onClick={() => handleMove(index, -1)}
                  title="上移"
                />
                <Button
                  type="text"
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={index === images.length - 1}
                  onClick={() => handleMove(index, 1)}
                  title="下移"
                />
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleRemove(index)}
                  title="删除"
                />
              </Space>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
