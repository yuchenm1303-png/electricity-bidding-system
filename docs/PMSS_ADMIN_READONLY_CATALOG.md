# PMSS 按工程授权的私有只读案例目录

本功能补齐 React 工作台的三个同源 GET 接口：
- `/api/pmss/read-only/projects`
- `/api/pmss/read-only/cases?project_id=...`
- `/api/pmss/read-only/snapshot?project_id=...&case_date=...`

## 安全边界

- **所有已登录用户均可调用只读接口**，但只有获明确共享授权的项目才会出现在普通成员列表中；没有显式授权时默认仅管理员可读。匿名 401、已登录成员未获工程授权 403、账号系统未启用 503。管理员功能（用户管理等）仍仅管理员使用。
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

必须启用 PowerBid 账号系统；未配置目录返回 503，不会提供虚构工程或回退合成案例，原有手动导入 JSON 保留。

### 面向所有已登录用户共享已授权教学案例

要让正常登录的普通账号也能选择某个工程，**必须先由教学数据权利方明确允许向该网站的所有注册账号共享**，再由受信任的服务器管理员在私有 `catalog.json` 对该工程额外设置：

```json
"visibility": "authenticated"
```

只有 `authenticated` 和 `admin_only` 两种值；省略时按 `admin_only` 处理。平台登录状态、PowerBid 会员身份、VPN 已接通均不等于学校数据共享授权。普通账号列表自动过滤未授权工程，即使猜到其工程 ID 也无法读取日期和快照（403）。此字段只允许在服务器私有目录中由可信人员配置，绝不能让注册用户自行修改。

导入标准模型时要核对原始 PMSS 工程、案例日期、电网、负荷和历史出清属于同一教学场景。尤其注意：`baseMva=1` 仍只是本地 DC 角度计算基准，不能宣称复现老师 SCUC/SCED。

## 验收

`pytest -q tests/test_pmss_readonly_catalog_api.py`

可用有权限的管理员账号在 PowerBid「PMSS 市场分析」选择工程/日期加载；对已明确配置 visibility=authenticated 的工程，再用普通成员账号完整测试工程/日期/快照。需另行验证最新生产容器已只读挂载私有目录；GitHub CI 不包含学校原始数据。没有新报价提交或经老师 PMSS 的因果出清验证时，只能称为**历史研究和本地策略试算**。
