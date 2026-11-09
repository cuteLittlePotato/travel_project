/**
 * M11 基础数据服务的契约测试（M11-T11）。
 *
 * 验证请求方法、路径、参数与后端 API 约定一致。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockRequest = vi.fn();

vi.mock('@/services/http', () => ({
  request: (...args: unknown[]) => mockRequest(...args),
}));

describe('catalog service', () => {
  beforeEach(() => {
    mockRequest.mockReset();
  });

  describe('地区', () => {
    it('listProvinces GET /regions/provinces', async () => {
      mockRequest.mockResolvedValue({ items: [] });
      const { listProvinces } = await import('./catalog');

      await listProvinces('北京');
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/regions/provinces',
        params: { keyword: '北京' },
      });
    });

    it('listCities 支持 province_id 与分页', async () => {
      mockRequest.mockResolvedValue({ items: [], total: 0 });
      const { listCities } = await import('./catalog');

      await listCities({ province_id: 'p1', page: 2, page_size: 20 });
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/regions/cities',
        params: { province_id: 'p1', page: 2, page_size: 20 },
      });
    });
  });

  describe('分类', () => {
    it('listCategories 支持类型筛选', async () => {
      mockRequest.mockResolvedValue({ items: [] });
      const { listCategories } = await import('./catalog');

      await listCategories('theme');
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attraction-categories',
        params: { category_type: 'theme' },
      });
    });
  });

  describe('景点', () => {
    it('listAttractions 支持全部筛选参数', async () => {
      mockRequest.mockResolvedValue({ items: [], total: 0 });
      const { listAttractions } = await import('./catalog');

      await listAttractions({
        city_id: 'c1',
        category_id: 'cat1',
        keyword: '故宫',
        is_published: true,
        page: 1,
        page_size: 10,
      });

      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attractions',
        params: {
          city_id: 'c1',
          category_id: 'cat1',
          keyword: '故宫',
          is_published: true,
          page: 1,
          page_size: 10,
        },
      });
    });

    it('getAttraction GET /attractions/{id}', async () => {
      mockRequest.mockResolvedValue({ id: 'a1' });
      const { getAttraction } = await import('./catalog');

      await getAttraction('a1');
      expect(mockRequest).toHaveBeenCalledWith({ url: '/attractions/a1' });
    });

    it('createAttraction POST /attractions', async () => {
      mockRequest.mockResolvedValue({ id: 'a1' });
      const { createAttraction } = await import('./catalog');

      await createAttraction({ name: '故宫', city_id: 'c1' });
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attractions',
        method: 'POST',
        data: { name: '故宫', city_id: 'c1' },
      });
    });

    it('updateAttraction PUT /attractions/{id}', async () => {
      mockRequest.mockResolvedValue(null);
      const { updateAttraction } = await import('./catalog');

      await updateAttraction('a1', { name: '新名', city_id: 'c1' });
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attractions/a1',
        method: 'PUT',
        data: { name: '新名', city_id: 'c1' },
      });
    });

    it('deleteAttraction DELETE /attractions/{id}', async () => {
      mockRequest.mockResolvedValue(null);
      const { deleteAttraction } = await import('./catalog');

      await deleteAttraction('a1');
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attractions/a1',
        method: 'DELETE',
      });
    });

    it('setAttractionCategories 用 PUT + category_ids（整体替换）', async () => {
      mockRequest.mockResolvedValue(null);
      const { setAttractionCategories } = await import('./catalog');

      await setAttractionCategories('a1', ['cat1', 'cat2']);
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attractions/a1/categories',
        method: 'PUT',
        data: { category_ids: ['cat1', 'cat2'] },
      });
    });

    it('setAttractionCategories 支持空数组（清空分类）', async () => {
      mockRequest.mockResolvedValue(null);
      const { setAttractionCategories } = await import('./catalog');

      await setAttractionCategories('a1', []);
      expect(mockRequest).toHaveBeenCalledWith({
        url: '/attractions/a1/categories',
        method: 'PUT',
        data: { category_ids: [] },
      });
    });
  });

  describe('错误传播', () => {
    it('后端错误 message 原样向上抛（删除引用场景）', async () => {
      mockRequest.mockRejectedValue(new Error('该景点已被引用（footprint 3 条），无法删除'));
      const { deleteAttraction } = await import('./catalog');

      await expect(deleteAttraction('a1')).rejects.toThrow('已被引用');
    });
  });
});
