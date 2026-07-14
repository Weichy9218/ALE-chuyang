# ALE Computer-Use 软件与任务对应清单

## 1. 范围与口径

本文档汇总当前 ALE 仓库中需要通过桌面界面进行点击、输入、浏览、编辑、建模、
播放或视觉检查的软件，并给出对应任务 ID。

## 2. 浏览器与 Web 应用

| 软件 | 版本或形态 | 对应任务 | Computer-use 用途 |
|---|---|---|---|
| Google Chrome | 149.0.7827.54 或 Linux Chrome | `business_finance/ar_full_300` | 从东方财富下载年报 |
| Google Chrome | 同上 | `business_finance/equity_research_summary` | 浏览 Yahoo Finance、SEC 页面 |
| Google Chrome | Linux 系统包 | `business_finance/ff5_public_reconstruction` | 使用任务提供的浏览器入口访问公开数据 |
| Google Chrome | 149.0.7827.54 | `business_finance/taxform_4_1` | 打开本地 W-2/1040 页面、填写表单并保存结果 |
| Google Chrome | 149.0.7827.54 | `physical_sciences/egt710_table1_smiles_extraction` | 阅读 PDF，并通过 ChemInfo 页面验证 SMILES |
| Microsoft Edge | 系统版 | `business_finance/ar_full_1500` | 下载大批量年报 PDF |
| Microsoft Edge | 系统版 | `business_finance/metabase_bi_dashboard_01` | 打开并操作本地 Metabase |
| Microsoft Edge | 系统版 | `physical_sciences/ketcher_smiles_reproduction` | 承载 Ketcher Web 应用 |
| Microsoft Edge | 系统版 | `physical_sciences/lenacapavir_sar_table2_extraction` | 阅读论文 PDF |
| Microsoft Edge PDF Viewer | 系统版 | `psychology_neuro/reddit_ai_post_codebook_boolean_coding` | 阅读心理学 codebook PDF |
| Metabase | 0.54.3 | `business_finance/metabase_bi_dashboard_01` | 创建和配置 BI Dashboard |
| Odoo | 19 | `business_finance/odoo` | 在 ERP Web UI 中处理库存、采购和物流流程 |
| PostgreSQL | 17 | `business_finance/odoo` | Odoo 的任务后端；一般不直接通过 GUI 操作 |
| Ketcher | 在线 Web 应用 | `physical_sciences/ketcher_smiles_reproduction` | 重画分子并导出 SMILES |
| ChemInfo SMILES Generator & Checker | 在线 Web 应用 | `physical_sciences/egt710_table1_smiles_extraction` | 验证重建的化学结构和 SMILES |
| UCSC Genome Browser | Web 应用 | `life_sciences/tp53_locus_variant_histone_browser_svg` | 加载 VCF、BigWig 并生成 TP53 位点 SVG |
| IGV / WashU Epigenome Browser | 可选替代 | `life_sciences/tp53_locus_variant_histone_browser_svg` | UCSC 的可替代基因组可视化工具 |

## 3. 办公、文档与基础桌面软件

| 软件 | 对应任务 | Computer-use 用途 |
|---|---|---|
| LibreOffice Calc | `business_finance/basel_operational_risk_bia_cn` | 处理和输出运营风险工作簿 |
| LibreOffice Calc | `business_finance/equity_research_summary` | 创建带公式的 Tesla 财务汇总工作簿 |
| LibreOffice Calc | `psychology_neuro/reddit_ai_post_codebook_boolean_coding` | 在工作簿中填写布尔编码列 |
| LibreOffice | `other/aerobics_wc2026_portugal_trio_difficulty_scoring` | 整理视频评分结果 |
| LibreOffice Writer 或其他 DOCX 编辑器 | `visual_media/video_storyboard_001` | 创建视频分镜 DOCX |
| Microsoft PowerPoint | `business_finance/saas_onepager_brand_refresh_instance_1` | 制作品牌化 SaaS 单页 |
| Visual Studio Code | `physical_sciences/lenacapavir_sar_table2_extraction` | 编辑 CSV、SMILES 或辅助文本 |
| Windows Image Viewer | `education_info/yi_manuscript_translation_1` | 查看手稿原始图像和边注 |
| Windows 文本编辑器 | `education_info/yi_manuscript_translation_1` | 编写报告和 JSON 输出 |

## 4. 三维、图形与游戏引擎

| 软件 | 版本 | 对应任务 | Computer-use 用途 |
|---|---:|---|---|
| Blender | 5.0.1 | `engineering/robotics_blender_tabletop_reconstruction` | 重建机器人桌面场景 |
| Blender | 4.5.1 LTS | `visual_media/atlas_outpost_graybox_navigation` | 制作灰盒场景资产 |
| Blender | 环境提供版本 | `visual_media/blender_character_reconstruction_from_multiview_01` | 根据多视图重建角色 |
| Blender | 5.0.1 | `visual_media/high_to_low_modeling` | 高模转低模 |
| Blender | 5.0.1 | `visual_media/human_mesh_animation_reproduction` | 生成人体网格动画序列 |
| Blender | 5.0.1 | `visual_media/object_generation` | 三维对象生成 |
| Blender | 5.0.1 | `visual_media/skeletal_animation_reproduction` | 骨骼动画复现 |
| Blender | 5.0.1 | `visual_media/uv_reproduction` | UV 展开复现 |
| Godot Engine | 4.6.2 | `visual_media/atlas_outpost_graybox_navigation` | 组装并验证可导航灰盒关卡 |
| Unreal Engine | 环境提供版本 | `visual_media/scene_restoration` | 打开脚手架项目并恢复场景 |
| Inkscape | 1.4.3 | `visual_media/inkscape_cultural_poster_design` | 创建文化主题矢量海报 |
| Ruffle | 0.2.0 | `other/mota_exploration` | 运行 SWF、推进游戏并截取楼层参考图 |
| Ruffle / Adobe Flash Player | 兼容运行时 | `visual_media/mota_reproduction` | 查看原始 Magic Tower Flash 游戏 |
| RPG Maker XP | 环境提供版本 | `visual_media/mota_reproduction` | 重制楼层、怪物和战斗逻辑 |

## 5. 视频、音频与动画软件

| 软件 | 版本 | 对应任务 | Computer-use 用途 |
|---|---:|---|---|
| Adobe After Effects | 环境提供版本 | `visual_media/butterfly_flap_animation` | 制作蝴蝶开合翅动画并导出 MP4 |
| DaVinci Resolve | 21.0 | `visual_media/chroma_key_from_reference` | 根据参考画面完成色键抠像和合成 |
| VLC | 3.0.21 | `visual_media/video_storyboard_001` | 播放源视频、定位镜头和时间点 |
| VLC | 3.0.21 | `other/aerobics_wc2026_portugal_trio_difficulty_scoring` | 观看比赛视频并识别难度动作 |
| Dorico | 6 | `visual_media/music_transcription` | 创建乐谱、录入声部并导出总谱图 |
| Cubase | 15 | `visual_media/project_migration` | 打开和迁移音乐工程、检查乐器或插入槽 |

## 6. CAD、EDA 与工程软件

| 软件 | 版本 | 对应任务 | Computer-use 用途 |
|---|---:|---|---|
| Rhino | 8 | `engineering/2d_drawings_to_3d_building_model` | 根据二维图纸建立建筑模型 |
| Rhino | 8 | `engineering/2d_drawings_to_3d_bridge_model` | 根据二维图纸建立桥梁模型 |
| Autodesk Civil 3D | 2024 | `engineering/cailian_road_highway_alignment_2` | 创建道路平面和纵断面设计 |
| Autodesk PowerMill | 2025 | `engineering/gcode` | 建立 CNC 刀路并检查碰撞、过切 |
| PLAXIS 3D | 2023.2 | `engineering/inner_support_elevation_optimization` | 进行基坑支撑标高优化和结果检查 |
| Moldex3D | 2025 | `engineering/mold-flow` | 载入工程并完成模流分析 |
| KiCad | 10.0.0 | `engineering/pcb_layout_kicad_1` | 从原理图创建 PCB 布局 |
| KiCad | 10.0.0 | `engineering/kicad_navswitch_library_integration_release_002` | 集成元件库并在桌面 UI 中检查项目 |
| LTspice | 环境预装 | `engineering/Analog_Active` | 补全 LTM4648 电路、运行瞬态仿真并截图 |
| Isaac Sim / Isaac Lab | GPU 环境 | `engineering/humanoid_velocity_tracking_policy` | 运行人形机器人策略仿真；主要评价路径可由命令启动 |
| Smokeview | 6.10.1，可选 | `transport_safety/fds_single_compartment_detector_reconstruction` | 对 FDS 火灾场景做专业可视化验证，不是提交硬门槛 |

## 7. 逆向工程与网络分析软件

| 软件 | 版本 | 对应任务 | Computer-use 用途 |
|---|---:|---|---|
| Ghidra | 11.3 | `computing_math/ghidra_malware_config_extraction_01` | 逆向可执行文件并恢复恶意程序配置 |
| JDK | 21 | `computing_math/ghidra_malware_config_extraction_01` | Ghidra 运行时，不直接作为业务 GUI 操作 |
| Wireshark | 4.4.14 | `computing_math/pcap_enterprise_triage_01` | 分析企业 PCAP 并整理网络事件 |
| `tris.exe` | 任务自带程序 | `computing_math/tris_crackme` | 启动注册程序、验证持久注册状态 |
| `crackme.exe` | 任务自带程序 | `computing_math/newyear_keygen2` | 可选启动分析；主要目标是推导动态密码 |

## 8. 医学、生命科学与专业可视化软件

| 软件 | 版本 | 对应任务 | Computer-use 用途 |
|---|---:|---|---|
| MicroDicom DICOM Viewer | 2025.3 | `health_medicine/microdicom_nih_cxr_reader_adjudication` | 打开胸片 DICOM 并完成病例判读 |
| 3D Slicer | 5.0.3 | `psychology_neuro/scene2_resample` | 最近邻重采样 ROI、统计并导出设置截图 |
| FSLeyes | 1.18.1 | `health_medicine/scene3_skullstrip_qc` | 对候选 skull-strip mask 做视觉 QC |
| POINTS | PyQt GUI | `psychology_neuro/celegans_neuron_tracking` | 查看和编辑 C. elegans 神经元追踪结果 |
| CellProfiler | 4.2.8 | `life_sciences/yeast_colony_detection` | 构建红色酵母菌落检测工作流 |
| CellProfiler | 环境提供版本 | `life_sciences/cell_translocation_analysis` | 细胞分割、对象测量和转位分析 |
| matRad | 固定任务环境 | `health_medicine/prostate_imrt_matrad_reproduction` | 放疗计划、剂量优化和 DICOM-RT 输出；也可脚本化运行 |
| GNU Octave | 6.4.0 | `health_medicine/prostate_imrt_matrad_reproduction` | matRad 计算和交互运行环境 |
| Sabaki | 0.52.2 | `computing_math/go_game_reconstruction_1` | 逐手重建棋局并导出 SGF |

## 9. 所有软件汇总

下面按软件名称或产品族去重汇总。不同版本的 Blender、Chrome 等合并为同一产品，
但功能独立的 Calc、Writer、Isaac Sim 和 Isaac Lab 分开列出。

### 9.1 任务中直接操作的软件

| 类别 | 软件汇总 |
|---|---|
| 浏览器 | Google Chrome、Microsoft Edge |
| Web/业务应用 | Metabase、Odoo、Ketcher、ChemInfo SMILES Generator & Checker |
| 基因组浏览器 | UCSC Genome Browser、IGV、WashU Epigenome Browser |
| 办公与编辑 | LibreOffice Calc、LibreOffice Writer、Microsoft PowerPoint、Visual Studio Code、Windows Image Viewer、Windows 文本编辑器 |
| 三维与游戏引擎 | Blender、Godot Engine、Unreal Engine、RPG Maker XP(license needed) |
| 矢量与图像设计 | Inkscape |
| 视频与动画 | Adobe After Effects、DaVinci Resolve、VLC |
| 音乐与乐谱 | Dorico(license needed)、Cubase(license needed) |
| Flash/SWF 运行 | Ruffle、Adobe Flash Player |
| CAD/CAM/CAE | Rhino(license needed)、Autodesk Civil 3D(license needed)、Autodesk PowerMill(license needed)、PLAXIS 3D(license needed)、Moldex3D(license needed) |
| EDA/电子设计 | KiCad、LTspice |
| 机器人仿真 | Isaac Sim、Isaac Lab |
| 火灾可视化 | Smokeview（可选验证） |
| 逆向与网络分析 | Ghidra、Wireshark |
| 医学影像 | MicroDicom DICOM Viewer、3D Slicer、FSLeyes |
| 生物与科研 GUI | POINTS、CellProfiler、matRad、Sabaki |
| 任务自带程序 | `tris.exe`、`crackme.exe` |

### 9.2 后端、运行时与配套软件

| 软件 | 配套对象或用途 |
|---|---|
| PostgreSQL 17 | Odoo 19 数据库后端 |
| JDK 21 | Ghidra 11.3 运行时 |
| GNU Octave 6.4.0 | matRad 计算和交互运行环境 |
| Apptainer 1.3.0 | 封装启动部分 Linux GUI，例如 3D Slicer/FSLeyes |
| Mesa3D | KiCad、Inkscape 等 GUI 的图形兼容层 |
| Python | 多个任务中的文件处理、自动化或结果生成辅助工具 |

### 9.3 总览

ALE 的 computer-use 软件栈覆盖：**浏览器与 Web 应用、Office 文档、三维建模、游戏引擎、
视频音频制作、CAD/CAM/CAE、EDA、逆向工程、网络分析、医学影像、生命科学 GUI、机器人仿真，
以及承载这些应用的 Windows/Linux 虚拟桌面基础设施**。
