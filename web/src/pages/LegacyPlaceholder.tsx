// v0.4 兼容路由 placeholder - 提示用户切到 v0.5 路由
import { Card, CardContent } from "@/components/ui/card";
import { Link } from "react-router-dom";

export function LegacyPlaceholder({ title, v0_5_path }: { title: string; v0_5_path: string }) {
  return (
    <div className="p-6">
      <Card>
        <CardContent className="p-8 text-center">
          <div className="text-2xl mb-2">⚠️ v0.4 {title} 已废弃</div>
          <div className="text-gray-500 mb-4">
            v0.5 阶段 1.5 初始化后, v0.4 API 写操作已 deprecated (返回 410 Gone).
            GET 仅用于历史数据查询.
          </div>
          <Link to={v0_5_path} className="text-blue-600 hover:underline">
            前往 v0.5 {v0_5_path} →
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
