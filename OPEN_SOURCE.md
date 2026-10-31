# FinSocratic 开源组件清单

本项目通过 `requirements.txt` 安装下列第三方 Python 包，并调用其公开 API。当前仓库没有复制其他金融平台的商标、专有界面、收费数据或整套应用源码。下表按项目直接依赖列出；实际安装版本可在运行环境中执行 `python -m pip freeze` 查看，间接依赖的许可证以安装包内的元数据与许可证文件为准。

| 组件 | 本项目用途 | 声明的许可 | 上游源码或许可 |
|---|---|---|---|
| Streamlit | 本地网页界面、上传、下载 | Apache-2.0 | [streamlit/streamlit LICENSE](https://github.com/streamlit/streamlit/blob/develop/LICENSE) |
| pandas | 表格导入、清洗、时间序列对齐 | BSD-3-Clause | [pandas LICENSE](https://github.com/pandas-dev/pandas/blob/main/LICENSE) |
| NumPy | 数值计算 | BSD-3-Clause（主项目；发布包可含其他许可的二进制组件） | [numpy LICENSE](https://github.com/numpy/numpy/blob/main/LICENSE.txt)、[打包许可说明](https://github.com/numpy/numpy/blob/main/pyproject.toml) |
| Plotly.py | 交互式净值与回撤图 | MIT | [plotly.py pyproject.toml](https://github.com/plotly/plotly.py/blob/main/pyproject.toml) |
| openpyxl | 读取 XLSX / XLSM | MIT/Expat | [openpyxl 官方文档](https://openpyxl.readthedocs.io/en/stable/index.html)、[源码](https://foss.heptapod.net/openpyxl/openpyxl) |
| pypdf | 提取文本型 PDF | BSD-3-Clause | [pypdf pyproject.toml](https://github.com/py-pdf/pypdf/blob/main/pyproject.toml) |
| python-docx | 提取 DOCX 段落与表格 | MIT | [python-docx pyproject.toml](https://github.com/python-openxml/python-docx/blob/master/pyproject.toml) |
| scikit-learn | 本地 TF-IDF 检索和余弦相似度 | BSD-3-Clause | [scikit-learn COPYING](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) |

## 复用范围与署名

- 项目直接依赖的版本范围见 [`requirements.txt`](requirements.txt)；本次验收环境的完整依赖快照见 [`requirements-lock.txt`](requirements-lock.txt)。依赖快照不能替代上游许可证。
- 本仓库的界面样式和 FOF 研究流程由项目代码实现。上表组件通过包管理器安装，不表示已并入这些项目的完整源码。
- 如将依赖包、静态资源或复制的组件源码一并打包分发，应保留相应上游版权声明、许可证以及适用的 `NOTICE` 文件；新增组件时先核对具体版本的授权条件，再更新本清单。
- 合成演示数据位于 `data/sample/`，不得当作真实基金业绩、管理人陈述或经外部机构验证的资料。外部数据即使公开可访问，其下载、处理与再分发条款仍须单独核对。


## 本轮产品集成

主工作台实际使用 React、Mantine、Tabler Icons、Recharts、react-markdown 和 remark-gfm；详见 frontend/NOTICE.md 与 package-lock.json。SciPy 为 BSD-3-Clause 数值依赖，requests 为 Apache-2.0。未引入 FinRobot 或 OpenBB 源码；研究架构参考不等于直接代码集成。公开基金数据和管理人披露不属于开源软件，来源与口径另见 PUBLIC_DATA.md。
