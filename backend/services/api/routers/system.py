from fastapi import APIRouter
from config.settings import settings
from backend.shared.version import get_version_info, check_updates

router = APIRouter(prefix="/api/v1/system", tags=["System"])


@router.get("/version")
async def system_version(force: bool = False):
    """当前运行代码版本与上游更新检查。

    - version/commit/branch：读取运行快照中的版本元数据。
    - update：可选地调用上游平台（默认 gitee）compare API 算出本部署落后提交数。
      无提交元数据或无法访问上游时省略；force=true 可绕过缓存强制刷新。
      更新检查只提供版本信息，不安装或发布更新，任何异常都不应影响版本读取接口。
    """
    info = get_version_info()
    try:
        update = await check_updates(force=force)
    except Exception:
        update = None
    return {
        "version": info["version"],
        "edition": settings.edition,
        "commit": info["commit"],
        "branch": info["branch"],
        "update": update,
    }


@router.get("/capabilities")
async def get_capabilities():
    """获取当前版本的系统能力与开关"""
    return settings.capabilities
