# IPTV Manager

![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/neon9809/iptv-manager/docker-build.yml?branch=main&style=for-the-badge)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/neon9809/iptv-manager?style=for-the-badge)

**IPTV Manager** 是一个功能强大的 IPTV (网络电视) 直播源管理和优化系统。它能帮助您轻松整合、管理和分析来自不同来源的 M3U 订阅源，自动进行频道匹配、流质量分析和稳定性评估，并为您生成优化后的、高质量的播放列表。

该项目基于 FastAPI (后端) 和 Vue.js (前端) 构建，并采用了一套健壮的、基于 Celery 和数据库的异步任务处理架构，确保了高效、可靠的直播流分析能力。

## 核心功能

- **多订阅源管理**: 轻松添加、刷新和管理多个 M3U 订阅源。
- **自动频道匹配**: 强大的别名匹配算法，能自动将来自不同源的、名称各异的直播流精准地归类到标准频道下。
- **深度流质量分析**:
  - **基础分析**: 快速检测延迟和码率。
  - **增强分析**: 深入分析视频编码、分辨率、帧率、稳定性等关键指标。
- **智能任务队列**: 基于优先级的自定义任务调度系统，确保关键任务（如手动分析）能优先执行，同时保证系统资源的合理利用。
- **统一通知系统**: 三条通知渠道（首页通知栏、最近维护面板、SMTP邮件），实时推送任务进度和系统状态。
- **配置备份恢复**: 一键导出/导入所有系统配置。
- **动态播放列表生成**: 根据不同的策略（如最快响应、最佳质量、最稳定）生成优化后的 M3U 播放列表。
- **Web 用户界面**: 提供直观的前端界面，方便您进行频道管理、流监控和系统配置。
- **多架构支持**: Docker 镜像同时支持 `linux/amd64` 和 `linux/arm64` 架构，方便在各种设备上部署。

## 快速开始

我们强烈建议使用 Docker Compose 进行部署，这是最简单、最可靠的方式。

### 使用 Docker Compose

1. **下载 `docker-compose.yml` 文件**

   ```bash
   curl -o docker-compose.yml https://raw.githubusercontent.com/neon9809/iptv-manager/main/docker-compose.yml
   ```

2. **创建必要的目录**

   ```bash
   mkdir -p app_data app_logo
   ```

3. **启动服务**

   ```bash
   docker-compose up -d
   ```

4. **访问应用**

   - **前端界面**: `http://<your-server-ip>:8001`
   - **后端 API**: `http://<your-server-ip>:8000`
   - **播放列表**: `http://<your-server-ip>:8001/playoptimized` (或其他策略)

### 端口说明

| 端口 | 服务 | 说明 |
|------|------|------|
| 8000 | Backend | FastAPI 后端服务，提供 REST API |
| 8001 | Frontend | Nginx 前端服务，提供 Web 界面 |
| 5432 | PostgreSQL | 数据库（容器内部） |
| 6379 | Redis | 缓存和消息队列（容器内部） |

> **注意**: 默认配置下，只有 8000 和 8001 端口对外暴露。数据库和 Redis 仅在 Docker 内部网络中可访问。

### 镜像说明

项目镜像托管在 GitHub Container Registry (ghcr.io)。

- **后端**: `ghcr.io/neon9809/iptv-manager-backend:latest`
- **前端**: `ghcr.io/neon9809/iptv-manager-frontend:latest`

`docker-compose.yml` 文件已默认使用这些镜像。当您执行 `docker-compose pull` 或 `docker-compose up` 时，会自动拉取最新的多架构镜像。

## 架构概览

IPTV Manager 采用现代化的微服务架构，主要包含以下组件：

- **Frontend (Vue.js + Nginx)**: 用户交互界面。
- **Backend (FastAPI)**: 提供核心 API 服务。
- **Celery Worker**: 异步执行耗时的分析任务。
- **Celery Beat**: 定时任务调度器，负责触发周期性任务。
- **PostgreSQL**: 主数据库，存储频道、直播流、任务等核心数据。
- **Redis**: 作为 Celery 的消息代理 (Broker) 和结果后端。

### 异步任务系统

本项目的核心亮点之一是其健壮的异步任务系统。我们没有直接依赖 Celery 的原生优先级（因为它需要 RabbitMQ 等更重的 Broker），而是实现了一套**基于数据库的应用层优先级队列**。

1. **Task 数据表**: 所有需要异步执行的操作（如刷新订阅源、分析直播流）都会先作为一条记录插入到 `tasks` 表中，并被赋予一个优先级。
2. **自定义调度器**: 一个高频运行的 Celery Beat 任务 (`dispatch_tasks`) 会定期扫描 `tasks` 表，按优先级拉取 `PENDING` 状态的任务。
3. **任务分发**: 调度器将拉取到的任务发送到 Celery 的不同队列中（如 `analysis-high`, `analysis`, `refresh`），交由 Worker 执行。

这个架构确保了：
- **真正的优先级**: 手动触发的单个流分析（优先级9）总能比自动的批量分析（优先级2）先被执行。
- **任务持久化与恢复**: 即使系统重启，所有未完成的任务状态都保存在数据库中，系统启动后会自动恢复，确保任务不会丢失。
- **灵活性与可扩展性**: 整个任务系统与消息代理解耦，未来可以轻松扩展新的任务类型和更复杂的调度逻辑。

## 致谢

本项目的开发和重构得到了以下 AI 工具的协助：

### v0.4.5 贡献者

**Trae IDE** 中的 **GLM-5** 模型完成了 v0.4.5 版本的主要开发工作，包括：

- **统一通知系统**: 设计并实现了 `NotificationDispatcher` 统一分发器，集成三条通知渠道
- **任务进度通知**: 为所有分析任务添加了实时进度推送功能
- **配置备份恢复**: 实现了完整的配置导出/导入功能
- **日志系统优化**: 修复了日志写入问题，添加了 Celery Beat 定时清理任务
- **M3U 格式修复**: 修复了播放列表 Content-Type，使其兼容各种播放器
- **UI/UX 优化**: 参照 Element Plus 设计规范优化了界面布局和手机适配
- **Bug 修复**: 解决了数据库连接池、Dockerfile 镜像源等问题

### 用户提示摘要

v0.4.5 版本的开发离不开用户的清晰指导和宝贵反馈：

1. **通知系统重构**: 用户发现原分析任务队列缺少通知模块集成，提出统一三条通知渠道的需求
2. **日志功能完善**: 用户指出设置面板日志功能不可用，并提出默认开启、定时清理的需求
3. **配置备份功能**: 用户发现备份/恢复按钮是摆设，要求实现完整功能
4. **播放列表格式**: 用户发现 M3U 格式不被播放器识别，需要修复
5. **UI 优化**: 用户参照 Element Plus 设计规范，要求优化手机适配和面板宽度
6. **端口映射说明**: 用户补充了后端 8000 端口映射，用于直接访问 API

这些高质量的互动极大地推动了项目的成功。

### v0.3.0 及之前贡献者

该项目最初由 **Manus AI** 协助开发和重构。特别感谢其在以下方面的贡献：

- **架构设计**: 提出了基于数据库的异步任务调度方案，解决了原始设计中的核心问题。
- **代码实现**: 完成了任务队列、调度器、执行器等核心模块的重构工作。
- **CI/CD**: 设计并编写了支持多架构构建的 Dockerfile 和 GitHub Actions 工作流。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
