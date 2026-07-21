# 第 6 天：月木关系与 M51 公开图像

## 月亮与木星位置关系

`starskill relationship` 读取 `examples/moon_jupiter_shanghai.json`，使用上海经纬度和 `Asia/Shanghai` 时区，按 20 分钟间隔计算 2026-03-20 19:00 至 23:00 的月亮、木星高度角和方位角，以及两者视角角距。

```powershell
python -m starskill relationship examples\moon_jupiter_shanghai.json `
  --output runs\day6_moon_jupiter\relationship.csv `
  --metadata runs\day6_moon_jupiter\relationship.json
```

真实输出包含 13 个采样点。角距从 `87.916939` 度下降到 `85.226663` 度。这里的“接近”只描述天球投影上的角距变化，不表示月亮和木星在三维空间中彼此靠近。

生产计算使用 Astropy 7.2 的内置太阳系星历、UTC 时间尺度、几何 AltAz、关闭大气折射与 IERS 自动下载。Skyfield 1.53/DE421 独立抽查显示：月亮高度差不超过 `0.002` 度，通常角量不超过 `0.006` 度；木星接近天顶时方位角最大差约 `0.031` 度，方向矢量差仍约 `0.004–0.005` 度。天顶附近方位角对微小位置差异高度敏感，因此单独采用 `0.04` 度方位角容差。

## M51 SDSS DR18 图像

`starskill fetch-image` 使用结构化参数访问 SDSS SkyServer DR18 图像裁剪端点：

`https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg`

请求坐标为 RA `202.4696` 度、Dec `47.1952` 度，比例尺 `0.396` 角秒/像素，尺寸 512×512。单次请求超时 30 秒，响应上限 5 MB，不需要认证、不需要分页，预期并验证恰好得到一张图像。

```powershell
python -m starskill fetch-image examples\m51_sdss_image.json `
  --output-dir runs\day6_m51 `
  --cache-dir cache\sdss
```

真实源 JPEG 为 19,685 字节，SHA-256 为：

`6a1f3aa2e3b77078d905d5b923e4ba9ebc9b9f05891df1863726ea3f52204e1d`

输出包括原始图 `data/m51_sdss.jpg`、展示图 `figures/m51_display.png` 和 `image_metadata.json`。处理仅包含 512×512 中心裁剪、0.5% 自动对比度、60 角秒比例尺与来源标注；元数据保留请求参数、访问时间、波段、像素尺度、许可提示、文件大小和哈希。第二次请求由 SHA-256 键控缓存返回。

## 数据安全与失败路径

- URL 使用结构化编码，不拼接可执行命令；
- 同时检查 HTTP `Content-Length` 和实际读取字节数；
- 检查 MIME、JPEG 格式和像素尺寸；
- 损坏缓存会被忽略，不作为有效数据复用；
- 无数据、服务失败、超限和内容校验失败分别返回退出码 `6`、`7`、`8`、`9`；
- 失败时不留下假图或伪造元数据。

SDSS 图像展示应遵守其图像使用政策并注明来源。当前功能只检索公开图像，不处理受限或需要认证的数据。
