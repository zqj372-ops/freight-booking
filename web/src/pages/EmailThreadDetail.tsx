// v0.5 EmailThread 详情页 (邮件对话流)
import { useQuery } from "@tanstack/react-query";
import { useParams, useNavigate, Link } from "react-router-dom";
import { v5Api, type EmailThreadWithMessages, type EmailMessage } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const DIRECTION_STYLES: Record<string, { icon: string; cls: string; align: string }> = {
  inbound: { icon: "←", cls: "bg-blue-50 border-blue-200", align: "self-start" },
  outbound: { icon: "→", cls: "bg-green-50 border-green-200", align: "self-end" },
};

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  queued: "排队中",
  sent: "已发",
  failed: "失败",
  received: "已收",
  processing: "处理中",
  processed: "已处理",
  ignored: "已忽略",
};

export function EmailThreadDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data, isLoading, error } = useQuery<EmailThreadWithMessages>({
    queryKey: ["email-thread", id],
    queryFn: () => v5Api.getEmailThread(id!),
    enabled: !!id,
  });

  if (isLoading) return <div className="p-8">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">{String(error)}</div>;
  if (!data) return <div className="p-8 text-gray-500">未找到</div>;

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => nav("/email-threads")}>
            ← 返回邮件线程
          </Button>
          <h1 className="text-2xl font-semibold mt-2 ml-2 inline-block">
            {data.subject}
          </h1>
          <div className="text-sm text-gray-500 mt-1">
            {data.subject_prefix && <span className="font-mono mr-2">{data.subject_prefix}</span>}
            {data.shipment_id && (
              <Link to={`/shipments/${data.shipment_id}`} className="text-blue-600 hover:underline">
                业务单: {data.shipment_id.slice(0, 8)}…
              </Link>
            )}
            <span className="ml-2">· 创建 {fmtDate(data.created_at)}</span>
            <span className="ml-2">· 最近活动 {fmtDate(data.updated_at)}</span>
          </div>
        </div>
        <Badge
          className={
            data.status === "active"
              ? "bg-green-100 text-green-800"
              : data.status === "closed"
              ? "bg-gray-200 text-gray-500"
              : "bg-red-100 text-red-800"
          }
        >
          {data.status}
        </Badge>
      </div>

      {/* 邮件对话流 */}
      <div className="space-y-3">
        {data.messages.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-gray-400">
              此线程暂无邮件
            </CardContent>
          </Card>
        ) : (
          data.messages.map((m) => <MessageCard key={m.id} m={m} />)
        )}
      </div>
    </div>
  );
}

function MessageCard({ m }: { m: EmailMessage }) {
  const style = DIRECTION_STYLES[m.direction] ?? DIRECTION_STYLES.inbound;
  const time = m.received_at ?? m.sent_at;

  return (
    <div className={`flex flex-col ${style.align} max-w-3xl`}>
      <Card className={`${style.cls} border`}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">{style.icon}</span>
              <Badge variant="outline">
                {m.direction === "inbound" ? "收件" : "发件"}
              </Badge>
              <span className="text-sm text-gray-500">
                {STATUS_LABELS[m.status] ?? m.status}
              </span>
              {m.match_confidence !== null && (
                <Badge className="bg-purple-100 text-purple-700 text-[10px]">
                  匹配 {Math.round(m.match_confidence * 100)}%
                </Badge>
              )}
            </div>
            <span className="text-xs text-gray-500">{fmtDate(time)}</span>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="text-sm space-y-1">
            <div>
              <span className="text-gray-500">发件人:</span>{" "}
              <span className="font-mono text-xs">{m.from_addr}</span>
            </div>
            <div>
              <span className="text-gray-500">收件:</span>{" "}
              <span className="font-mono text-xs">{m.to_addrs.join(", ")}</span>
            </div>
            {m.cc_addrs.length > 0 && (
              <div>
                <span className="text-gray-500">抄送:</span>{" "}
                <span className="font-mono text-xs">{m.cc_addrs.join(", ")}</span>
              </div>
            )}
            <div>
              <span className="text-gray-500">主题:</span>{" "}
              <span>{m.subject}</span>
            </div>
            {m.matched_shipment_id && (
              <div>
                <span className="text-gray-500">匹配业务单:</span>{" "}
                <Link
                  to={`/shipments/${m.matched_shipment_id}`}
                  className="text-blue-600 hover:underline font-mono text-xs"
                >
                  {m.matched_shipment_id.slice(0, 8)}…
                </Link>
              </div>
            )}
            {m.error && (
              <div className="text-red-600 text-xs mt-1">
                ⚠ 错误: {m.error}
              </div>
            )}
          </div>
          <div className="border-t pt-2 mt-2">
            {m.body_text ? (
              <pre className="whitespace-pre-wrap text-sm font-sans">{m.body_text}</pre>
            ) : m.body_html ? (
              <div
                className="text-sm"
                dangerouslySetInnerHTML={{ __html: m.body_html }}
              />
            ) : (
              <div className="text-gray-400 text-sm">(无正文)</div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return s;
  }
}
