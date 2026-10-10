# PMSS 管理员只读案例目录

本功能补齐 React 工作台的三个同源 GET 接口：
- `/api/pmss/read-only/projects`
- `/api/pmss/read-only/cases?project_id=...`
- `/api/pmss/read-only/snapshot?project_id=...&case_date=...`

## 安全边界

- **仅 PowerBid 已登录管理员**可以读取；普通账号 403、匿名 401、停用账号或未启用的账号系统 503。
- 仅从管理员在可信服务器显式配置的 **私有快照目录**加载；生产接口自身不访问老师平台、VPN，也不持有其 Cookie 或密码。
- 不把私有快照上传到仓库或嵌入前端镜像。服务器目录必须不在任何公共静态目录/Git 工作树之内；只读挂载到容器。
- 拒绝目录遍历、符号链接、重复工程或重复日期、错误来源、错误日期及敏感字段；历史结果不得冒充新报价验证。
- 全部响应禁用缓存；完全无报价提交和出清调用。

## 配置（管理员在有权使用该教学案例的可信服务器上操作）

将经过 `scripts/import_pmss_model.py` 严格验证的 `powerbid.pmss.standard.v1` 私有历史案例保存到专用目录（不覆盖、不上传 GitHub），并在相同目录建立 `catalog.json`：

```json
{
  "projects": [
    {
      "project_id": "pmss-group-2",
      "name": "获授权小组工程",
      "cases": [
        {"case_date": "2025-09-01", "file": "group2-2025-09-01.json"}
      ]
    }
  ]
}
```

上面的工程 ID 只是 PowerBid 内部别名，**不能**填写课程密码或会话标识。示例文件名为占位符，不是仓库提供的数据文件。

通过容器只读挂载 `/private/powerbid-pmss`，配置：

```
POWERBID_PMSS_READONLY_DIR=/private/powerbid-pmss
```

必须同时启用 PowerBid 账号系统，并只允许明确授权的管理员访问。未配置目录则返回 503，不会提供伪造工程或回退合成案例；原有手动导入 JSON 保留。

导入标准模型时要核对原始 PMSS 工程、案例日期、电网、负荷和历史出清属于同一教学场景。尤其注意：`baseMva=1` 仍只是本地 DC 角度计算基准，不能宣称复现老师 SCUC/SCED。

## 验收

`pytest -q tests/test_pmss_readonly_catalog_api.py`

可用有权限的管理员账号在 PowerBid「PMSS 市场分析」选择工程/日期加载。需另行验证最新生产容器已只读挂载私有目录；GitHub CI 不包含学校原始数据。没有新报价提交或经老师 PMSS 的因果出清验证时，只能称为**历史研究和本地策略试算**。
