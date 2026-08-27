// v0.6 预报 CSV 导入
import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { v6Api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const SAMPLE_CSV = `customer_id,customer_name,pol,pod,container_type,container_count,target_etd,source_ref,commodity
__CUSTOMER_ID__,客户A,CNSHA,USLAX,40HQ,1,2026-09-15,WO-001,Tools
__CUSTOMER_ID__,客户A,CNNGB,DEHAM,40GP,2,2026-09-16,WO-002,Toys`;

export function ForecastImport() {
  const nav = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [source, setSource] = useState("sales");
  const [sourceRefPrefix, setSourceRefPrefix] = useState("");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doImport() {
    if (!file) {
      setError("请选择 CSV 文件");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const r = await v6Api.importCsv(file, {
        dry_run: dryRun,
        source,
        source_ref_prefix: sourceRefPrefix || undefined,
      });
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">CSV 导入预报</h1>
        <Button variant="outline" onClick={() => nav("/forecasts")}>← 返回</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>1. CSV 格式 (header 必填)</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="bg-gray-50 p-3 rounded text-xs overflow-x-auto">{SAMPLE_CSV}</pre>
          <p className="text-xs text-gray-500 mt-2">
            注: 替换 <code>__CUSTOMER_ID__</code> 为实际 customer_id, 多源同 fingerprint 自动 confirm
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2. 上传 + 预判 / 导入</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm"
            />
            {file && <p className="text-xs text-gray-500 mt-1">已选: {file.name} ({file.size} bytes)</p>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm">source</label>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
                className="block w-full border rounded px-2 py-1 text-sm"
              >
                <option value="sales">物友销售</option>
                <option value="customer_service">客服</option>
                <option value="shending">深鼎</option>
                <option value="subsidiary">分子公司</option>
                <option value="manual">人工补录</option>
              </select>
            </div>
            <div>
              <label className="text-sm">source_ref_prefix (防同 file 撞 UNIQUE)</label>
              <input
                value={sourceRefPrefix}
                onChange={(e) => setSourceRefPrefix(e.target.value)}
                placeholder="e.g. 2026-08-27-imp-001"
                className="block w-full border rounded px-2 py-1 text-sm"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="dryrun"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            <label htmlFor="dryrun" className="text-sm">
              Dry run (只检测 dedup, 不入库)
            </label>
          </div>
          <Button disabled={loading || !file} onClick={doImport}>
            {loading ? "处理中..." : dryRun ? "预判" : "真实导入"}
          </Button>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-red-400">
          <CardContent className="p-4 text-red-600 text-sm">错误: {error}</CardContent>
        </Card>
      )}

      {result && (
        <Card>
          <CardHeader>
            <CardTitle>结果</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex gap-3">
              <Badge className="bg-green-100 text-green-800">新建 {result.created}</Badge>
              <Badge className="bg-yellow-100 text-yellow-800">疑似重复 {result.duplicates}</Badge>
              <Badge className="bg-red-100 text-red-800">错误 {result.errors.length}</Badge>
            </div>
            {result.errors.length > 0 && (
              <div className="mt-2">
                <div className="font-semibold text-red-600">错误详情:</div>
                <ul className="list-disc pl-5 text-xs text-gray-600">
                  {result.errors.map((e: any, i: number) => (
                    <li key={i}>
                      row {e.row?.row ?? e.row}: {e.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-2">
              <div className="font-semibold">dedup 明细 ({result.details.length} 条):</div>
              <div className="space-y-1 max-h-96 overflow-y-auto mt-1">
                {result.details.map((d: any, i: number) => (
                  <div key={i} className="text-xs flex gap-2">
                    <Badge
                      className={
                        d.action === "create_new" ? "bg-green-100 text-green-800" :
                        d.action === "merge_into_existing" ? "bg-blue-100 text-blue-800" :
                        "bg-yellow-100 text-yellow-800"
                      }
                    >
                      {d.action}
                    </Badge>
                    <span className="text-gray-700">{d.note}</span>
                    {d.match_count > 0 && (
                      <span className="text-orange-600">({d.match_count} 命中)</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
