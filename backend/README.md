# Backend（MuseCoco + post_operation + AR-VAE）

## 克隆

若含 **AR-VAE 子模块**：

```bash
git clone --recursive <你的仓库 URL>.git
# 若已克隆但未拉子模块：
git submodule update --init --recursive
```

## 体积说明（本仓库已 `.gitignore`）

- **MuseCoco Stage2 权重**、fairseq `data-bin`、本地 **runs/**、**infer_test.bin** 等：需自行放到对应路径或按组内文档下载。
- **AR-VAE**：父仓库只记录 **submodule 指针**；权重与 `data/` 在子模块内忽略，需本地训练或拷贝。
- 已把若干 **大二进制 / 重复 legacy 权重** 从 Git 索引移除（仍保留在你磁盘上，仅不再随仓库推送）。

## 运行

```bash
export MUSECOCO_PYTHON=/path/to/conda/envs/MuseCoco/bin/python
# 可选：POST_OPERATION_ROOT、ARVAE_CKPT、BACKEND_PUBLIC_BASE_URL
BACKEND_HOST=0.0.0.0 bash start_backend.sh
```

API 文档：`http://<host>:8000/docs`

## 推送到 GitHub（首次）

```bash
cd /path/to/Backend
git remote add origin https://github.com/<user>/<repo>.git   # 若尚未添加
git add -A
git status   # 确认无意外的大文件
git commit -m "chore: sync backend, trim large blobs from git"
git push -u origin main
```

若 **AR-VAE** 单独有远程，在 `ar-vae/` 子模块目录内再 `git push` 一次。
