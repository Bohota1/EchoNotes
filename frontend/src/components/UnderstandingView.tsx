/**
 * Renders one note's understanding result.
 *
 * Shared by the capture panel and the note detail view, so a note looks the
 * same whether you just recorded it or opened it from the list.
 *
 * Two accessibility rules shape this:
 *   - Nothing is conveyed by colour alone. The note type is a word; the quality
 *     score is a word plus a number, never a coloured bar on its own.
 *   - Empty categories are omitted rather than rendered empty, so a screen
 *     reader is not read four "no items" headings on every note.
 */

import type { Understanding } from "@/types";

function describeQuality(score: number): string {
  if (score >= 0.75) return "high";
  if (score >= 0.55) return "good";
  if (score >= 0.35) return "mixed";
  return "low";
}

function EntityList({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div className="entity-group">
      <h4>{label}</h4>
      <ul>
        {values.map((value) => (
          <li key={`${label}-${value}`}>{value}</li>
        ))}
      </ul>
    </div>
  );
}







export function UnderstandingView({
  understanding,
}: {
  understanding: Understanding;
}) {
  const { classification, quality } = understanding;

  return (
    <div className="understanding">
      <p className="badges">
        <span className={`badge badge-${understanding.note_type}`}>
          {understanding.note_type}
        </span>
        <span className="badge badge-quiet">
          {Math.round(classification.confidence * 100)}% confident
        </span>
        <span className="badge badge-quiet">via {classification.method}</span>
      </p>

      {classification.rationale && (
        <p className="muted small">Why: {classification.rationale}</p>
      )}

      <EntityList label="People" values={understanding.people} />
      <EntityList label="Deadlines" values={understanding.deadlines} />
      <EntityList label="Dates" values={understanding.dates} />
      <EntityList label="Tasks" values={understanding.tasks} />
      <EntityList label="Key phrases" values={understanding.key_phrases} />

      <details className="quality">
        <summary>
          Quality: {describeQuality(quality.quality_score)} (
          {quality.quality_score.toFixed(2)})
        </summary>
        <table>
          <tbody>
            <tr>
              <th scope="row">Readability</th>
              <td>{quality.readability.toFixed(2)}</td>
            </tr>
            <tr>
              <th scope="row">Coherence</th>
              <td>{quality.coherence.toFixed(2)}</td>
            </tr>
            <tr>
              <th scope="row">Transcription confidence</th>
              <td>{quality.transcription_confidence.toFixed(2)}</td>
            </tr>
            <tr>
              <th scope="row">Words</th>
              <td>{quality.word_count}</td>
            </tr>
            <tr>
              <th scope="row">Sentences</th>
              <td>{quality.sentence_count}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </div>
  );
}
