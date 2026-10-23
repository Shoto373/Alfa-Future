"use client";

import { useEffect, useState } from "react";
import CompanyPanel from "@/components/CompanyPanel";
import { Card, ErrorBox, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useCompany } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Meta } from "@/lib/types";
import common from "@/styles/common.module.scss";
import styles from "@/app/(bank)/company/page.module.scss";

export default function CompanyPage() {
  const { session } = useSession();
  const company = useCompany(session!.companyId);
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta(null)); }, []);
  const sectors = Object.fromEntries((meta?.sectors ?? []).map((s) => [s.sector, s.name]));

  return (
    <div className={`${common.page} ${styles.companyPage}`}>
      <div className={common.pageHead}>
        <div>
          <h1>{session!.companyName}</h1>
          <p className={common.muted}>Профиль по данным кейса: на этих признаках строится лента и разборы Альфа.Пульса.</p>
        </div>
      </div>
      {company.loading && <Card title="Профиль компании"><Skeleton lines={8} /></Card>}
      {company.error && <ErrorBox message={company.error.message} onRetry={company.reload} />}
      {company.data && (
        <CompanyPanel title="Профиль компании" profile={company.data.profile} exposures={company.data.exposures} sectors={sectors} />
      )}
    </div>
  );
}
