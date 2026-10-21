import type { Insight } from "@/lib/types";

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="card-section">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="muted">Нет данных</p>
      ) : (
        <ul>
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function InsightCard({ insight }: { insight: Insight }) {
  return (
    <article className="panel card" aria-label="Карточка анализа">
      <div className="badges">
        <span className="badge badge-test">Тестовые данные</span>
        <span className="badge badge-nollm">Анализ без LLM</span>
        {insight.is_mock && <span className="badge">Тестовая карточка</span>}
      </div>
      <h2>{insight.title}</h2>

      <section className="card-section">
        <h3>Почему это касается компании</h3>
        <p>{insight.company_relevance}</p>
      </section>

      <List title="Факты" items={insight.facts} />
      <List title="Риски" items={insight.risks} />
      <List title="Возможности" items={insight.opportunities} />
      <List title="Действия" items={insight.actions} />
      <List title="Неопределенность" items={insight.uncertainty} />

      <section className="card-section">
        <h3>Позиция банка</h3>
        <p className="muted">{insight.bank_position ?? "Аналитика банка еще не подключена"}</p>
      </section>

      <section className="card-section">
        <h3>Вывод модели</h3>
        <p>{insight.model_conclusion}</p>
      </section>

      <section className="card-section">
        <h3>Источники</h3>
        {insight.sources.length === 0 ? (
          <p className="muted">Нет данных</p>
        ) : (
          <ul>
            {insight.sources.map((s) => (
              <li key={s.source_id}>
                {s.title} <span className="muted">({s.kind === "synthetic_fixture" ? "синтетический fixture" : s.kind}, {s.source_id})</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="muted card-meta">
        request_id: {insight.request_id} · schema {insight.schema_version}
      </footer>
    </article>
  );
}
