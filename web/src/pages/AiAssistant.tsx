// v0.6.1 全局 AI 助手 - 问答 (mock LLM)
// 路径: /ai-assistant
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { v6ExceptionApi, type ExceptionAiAnswer } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const QUICK_QUESTIONS = [
  "现在有多少个未关闭的异常?",
  "shipment 总数是多少?",
  "本周预报有多少条?",
  "最近 7 天有哪些 critical 异常?",
];

interface Message {
  role: "user" | "ai";
  text: string;
  meta?: ExceptionAiAnswer;
}

export function AiAssistant() {
  const [input, setInput] = useState("");
  const [history, setHistory] = useState<Message[]>([]);

  const askMut = useMutation({
    mutationFn: (q: string) => v6ExceptionApi.askAi(q),
    onSuccess: (ans, q) => {
      setHistory((h) => [
        ...h,
        { role: "ai", text: ans.answer, meta: ans },
      ]);
    },
    onError: (e) => {
      setHistory((h) => [
        ...h,
        { role: "ai", text: `❌ 错误: ${String(e)}` },
      ]);
    },
  });

  const send = (q: string) => {
    if (!q.trim()) return;
    setHistory((h) => [...h, { role: "user", text: q }]);
    setInput("");
    askMut.mutate(q);
  };

  return (
    <div className="p-6 space-y-4 max-w-4xl">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">🤖 AI 助手</h1>
        <Badge variant="secondary" className="text-[10px]">v0.6 mock LLM</Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>问任何业务问题</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* 快捷问题 */}
          {history.length === 0 && (
            <div className="space-y-2">
              <div className="text-xs text-slate-500">试试这些问题:</div>
              <div className="flex flex-wrap gap-2">
                {QUICK_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="text-xs border rounded-full px-3 py-1 hover:bg-slate-50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 历史 */}
          {history.length > 0 && (
            <div className="space-y-3 max-h-[60vh] overflow-y-auto">
              {history.map((m, i) => (
                <div
                  key={i}
                  className={`p-3 rounded ${
                    m.role === "user"
                      ? "bg-sky-50 border-l-4 border-sky-400"
                      : "bg-emerald-50 border-l-4 border-emerald-400"
                  }`}
                >
                  <div className="text-xs text-slate-500 mb-1">
                    {m.role === "user" ? "👤 你" : "🤖 AI"} ·{" "}
                    {m.meta?.model || ""}
                  </div>
                  <div className="text-sm whitespace-pre-wrap">{m.text}</div>
                  {m.meta && m.meta.confidence != null && (
                    <div className="text-[10px] text-slate-400 mt-1">
                      置信度 {(m.meta.confidence * 100).toFixed(0)}%
                      {m.meta.sources.length > 0 && (
                        <> · 数据源: {m.meta.sources.join(", ")}</>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 输入 */}
          <div className="flex gap-2 border-t pt-3">
            <input
              className="flex-1 border rounded px-3 py-2 text-sm"
              placeholder="问点什么 (e.g. 最近 7 天有哪些 critical 异常)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              disabled={askMut.isPending}
            />
            <Button
              onClick={() => send(input)}
              disabled={!input.trim() || askMut.isPending}
            >
              {askMut.isPending ? "思考中..." : "发送"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
