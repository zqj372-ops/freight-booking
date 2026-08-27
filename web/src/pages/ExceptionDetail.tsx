// v0.6.1 异常 AI 跟进 - 异常详情 timeline
// 路径: /exceptions/:id
import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { v6ExceptionApi, v5Api, type ExceptionUpdate, type ExceptionFetchJob } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const SEVERITY_CLS: Record<string, string> = {
  info: "bg-blue-100 text-blue-700",
  warning: "bg-yellow-100 text-yellow-700",
  critical: "bg-red-100 text-red-700",
};

const STATUS_CLS: Record<string, string> = {
  open: "bg-orange-100 text-orange-700",
  resolved: "bg-green-100 text-green-700",
  auto_closed: "bg-gray-100 text-gray-700",
};

const UPDATE_TYPE_CLS: Record<string, string> = {
  ai_fetch: "bg-sky-100 text-sky-700",
  ai_summary: "bg-indigo-100 text-indigo-700",
  ai_suggestion: "bg-purple-100 text-purple-700",
  user_note: "bg-emerald-100 text-emerald-700",
  user_response: "bg-emerald-200 text-emerald-800",
  status_change: "bg-gray-100 text-gray-700",
};

const UPDATE_TYPE_LABEL: Record<string, string> = {
  ai_fetch: "AI 抓取",
  ai_summary: "AI 摘要",
  ai_suggestion: "AI 建议",
  user_note: "用户备注",
  user_response: "采纳 AI",
  status_change: "状态变更",
};

const SOURCE_LABEL: Record<string, string> = {
  carrier_website: "船公司网站",
  email: "邮件",
  wechat: "企微",
  user: "用户",
  ai_inference: "AI 推断",
};

const JOB_STATUS_CLS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  running: "bg-blue-100 text-blue-700",
  done: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-gray-200 text-gray-500",
};

const JOB_STATUS_LABEL: Record<string, string> = {
  pending: "待跑",
  running: "执行中",
  done: "完成",
  failed: "失败",
  cancelled: "已取消",
};

function UpdateRow({ u }: { u: ExceptionUpdate }) {
  return (
    <div className="border-l-2 border-slate-200 pl-3 py-2">
      <div className="flex items-center gap-2 mb-1">
        <Badge className={UPDATE_TYPE_CLS[u.update_type] || "bg-gray-100"}>
          {UPDATE_TYPE_LABEL[u.update_type] || u.update_type}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {SOURCE_LABEL[u.source] || u.source}
        </Badge>
        {u.ai_confidence != null && (
          <span className="text-[10px] text-slate-400">
            AI 置信度 {(u.ai_confidence * 100).toFixed(0)}%
          </span>
        )}
        <span className="text-[10px] text-slate-400 ml-auto">
          {new Date(u.created_at).toLocaleString("zh-CN")}
        </span>
        {u.created_by_user_name && (
          <span className="text-[10px] text-emerald-600">by {u.created_by_user_name}</span>
        )}
      </div>
      <div className="text-sm text-slate-700 whitespace-pre-wrap">{u.summary}</div>
      {u.raw_data && Object.keys(u.raw_data).length > 0 && (
        <details className="mt-1">
          <summary className="text-[10px] text-slate-400 cursor-pointer hover:text-slate-600">
            查看原始数据
          </summary>
          <pre className="text-[10px] bg-slate-50 p-2 rounded mt-1 overflow-x-auto">
            {JSON.stringify(u.raw_data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function FetchJobRow({ j }: { j: ExceptionFetchJob }) {
  return (
    <div className="flex items-center gap-2 py-1.5 text-xs">
      <Badge className={JOB_STATUS_CLS[j.status] || "bg-gray-100"}>
        {JOB_STATUS_LABEL[j.status] || j.status}
      </Badge>
      <span className="text-slate-600">{SOURCE_LABEL[j.source] || j.source}</span>
      <span className="text-slate-400">第 {j.run_count}/{j.max_runs} 次</span>
      {j.last_run_at && (
        <span className="text-slate-400">
          上次: {new Date(j.last_run_at).toLocaleString("zh-CN")}
        </span>
      )}
      {j.last_error && <span className="text-red-500 truncate max-w-xs">err: {j.last_error}</span>}
      <span className="text-slate-400 ml-auto">
        下次: {new Date(j.next_run_at).toLocaleString("zh-CN")}
      </span>
    </div>
  );
}

export function ExceptionDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [accept, setAccept] = useState(false);

  const q = useQuery({
    queryKey: ["exception-timeline", id],
    queryFn: () => v6ExceptionApi.getTimeline(id!),
    enabled: !!id,
    refetchInterval: 30_000, // 30s 自动刷新
  });

  const fetchNowMut = useMutation({
    mutationFn: () => v6ExceptionApi.fetchNow(id!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exception-timeline", id] }),
  });

  const addUpdateMut = useMutation({
    mutationFn: () => v6ExceptionApi.addUpdate(id!, note || "用户备注", accept),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["exception-timeline", id] });
      setNote("");
      setAccept(false);
    },
  });

  const acceptMut = useMutation({
    mutationFn: () => v6ExceptionApi.acceptSuggestion(id!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exception-timeline", id] }),
  });

  if (q.isLoading) return <div className="p-8">加载中...</div>;
  if (q.isError) return <div className="p-8 text-red-600">加载失败: {String(q.error)}</div>;
  const tl = q.data!;

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => nav("/exceptions")}>
          ← 返回
        </Button>
        <h1 className="text-2xl font-semibold">异常详情 (AI 跟进)</h1>
      </div>

      {/* 异常元信息 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>{tl.code}</span>
            <Badge className={SEVERITY_CLS[tl.severity]}>{tl.severity}</Badge>
            <Badge className={STATUS_CLS[tl.status]}>{tl.status}</Badge>
            <Link
              to={`/shipments/${tl.shipment_id}`}
              className="ml-auto text-sm text-sky-600 hover:underline"
            >
              查看 shipment →
            </Link>
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-1">
          <div>
            <span className="text-slate-500">检测时间:</span>{" "}
            {new Date(tl.detected_at).toLocaleString("zh-CN")}
          </div>
          {tl.resolved_at && (
            <div>
              <span className="text-slate-500">解决时间:</span>{" "}
              {new Date(tl.resolved_at).toLocaleString("zh-CN")}
            </div>
          )}
          {tl.resolution && (
            <div>
              <span className="text-slate-500">解决方式:</span> {tl.resolution}
            </div>
          )}
        </CardContent>
      </Card>

      {/* AI 最新建议 */}
      {tl.latest_ai_suggestion && tl.status === "open" && (
        <Card className="border-purple-300 bg-purple-50/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-purple-900">
              <span>💡 AI 最新建议</span>
              {tl.latest_ai_confidence != null && (
                <Badge variant="outline" className="text-[10px]">
                  置信度 {(tl.latest_ai_confidence * 100).toFixed(0)}%
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-slate-700 whitespace-pre-wrap mb-3">
              {tl.latest_ai_suggestion}
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => acceptMut.mutate()}
                disabled={acceptMut.isPending}
              >
                {acceptMut.isPending ? "处理中..." : "采纳并关闭异常"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => fetchNowMut.mutate()}
                disabled={fetchNowMut.isPending}
              >
                {fetchNowMut.isPending ? "跟进中..." : "立即再跟进一次"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 操作区 */}
      {tl.status === "open" && (
        <Card>
          <CardHeader>
            <CardTitle>加备注 / 操作</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={3}
              placeholder="备注内容 (e.g. 已电话联系客户, 暂不催)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="flex items-center gap-2">
              <label className="text-sm flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={accept}
                  onChange={(e) => setAccept(e.target.checked)}
                />
                <span>同时采纳 AI 建议并关闭异常</span>
              </label>
              <Button
                size="sm"
                onClick={() => addUpdateMut.mutate()}
                disabled={!note.trim() || addUpdateMut.isPending}
                className="ml-auto"
              >
                {addUpdateMut.isPending ? "提交中..." : "提交"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 抓取任务 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>抓取任务</span>
            <Badge variant="outline">{tl.fetch_jobs.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {tl.fetch_jobs.length === 0 ? (
            <div className="text-sm text-slate-400">暂无抓取任务</div>
          ) : (
            <div className="space-y-1">
              {tl.fetch_jobs.map((j) => (
                <FetchJobRow key={j.id} j={j} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Timeline */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>Timeline</span>
            <Badge variant="outline">{tl.updates.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {tl.updates.length === 0 ? (
            <div className="text-sm text-slate-400">暂无 update</div>
          ) : (
            <div className="space-y-2">
              {tl.updates.map((u) => (
                <UpdateRow key={u.id} u={u} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
