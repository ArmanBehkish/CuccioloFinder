function StatsTabs({ tabs, activeKey, onChange }) {
  return (
    <div className="stats-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          aria-selected={t.key === activeKey}
          className={`stats-tab${t.key === activeKey ? ' active' : ''}`}
          onClick={() => onChange(t.key)}
        >
          {t.icon && <span className="stats-tab-icon">{t.icon}</span>}
          {t.label}
        </button>
      ))}
    </div>
  );
}

export default StatsTabs;
