import Link from "next/link";

const TILES = [
  { title: "Счета и платежи", note: "Недоступно в демо" },
  { title: "Кредиты", note: "Недоступно в демо" },
  { title: "Депозиты", note: "Недоступно в демо" },
  { title: "Документы", note: "Недоступно в демо" },
];

export default function HomePage() {
  return (
    <main className="page">
      <header className="page-header">
        <h1>Альфа-Бизнес · демо</h1>
        <p className="muted">Макет главного экрана для проверки сценария новостной аналитики.</p>
      </header>

      <section className="hero">
        <div>
          <h2>Новостная аналитика</h2>
          <p>
            Выберите компанию и роль — сервис покажет, как учебное событие может касаться бизнеса. В этом спринте
            карточка формируется по правилам на тестовых данных, без LLM.
          </p>
        </div>
        <Link className="button button-primary" href="/analytics">
          Открыть новостную аналитику
        </Link>
      </section>

      <section className="tiles" aria-label="Другие разделы (не подключены)">
        {TILES.map((tile) => (
          <div className="tile tile-disabled" key={tile.title} aria-disabled="true">
            <strong>{tile.title}</strong>
            <span className="muted">{tile.note}</span>
          </div>
        ))}
      </section>
    </main>
  );
}
