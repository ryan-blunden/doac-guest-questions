import rawQuestions from "../../questions.json";

export type Question = {
  slug: string;
  title: string;
  video_url: string;
  question: string;
  category: string;
  question_extraction: string;
  confidence: number;
  hidden: boolean;
};

export const questions = (rawQuestions as Question[])
  .filter((item) => !item.hidden)
  .slice()
  .sort((a, b) => {
    return a.question.localeCompare(b.question);
  });

export const categoryMeta: Record<string, { label: string; note: string }> = {
  beliefs: {
    label: "Beliefs",
    note: "Faith, truth, meaning, and the structures people build around them.",
  },
  business: {
    label: "Business",
    note: "Money, work, leadership, ambition, and building something that lasts.",
  },
  general: {
    label: "General",
    note: "Questions that resist a narrower label and stay open on purpose.",
  },
  health: {
    label: "Health",
    note: "Body, mind, recovery, and the habits that shape how we feel.",
  },
  life: {
    label: "Life",
    note: "Identity, regret, courage, change, and the way someone chooses to live.",
  },
  relationships: {
    label: "Relationships",
    note: "Love, family, friendship, trust, and being understood by other people.",
  },
  society: {
    label: "Society",
    note: "Technology, politics, culture, and where the world might be heading.",
  },
};

export const categories = Object.entries(
  questions.reduce<Record<string, number>>((acc, item) => {
    acc[item.category] = (acc[item.category] ?? 0) + 1;
    return acc;
  }, {}),
)
  .map(([slug, count]) => ({
    slug,
    count,
    label: categoryMeta[slug]?.label ?? slug,
    note: categoryMeta[slug]?.note ?? "A slice of the archive.",
  }))
  .sort((a, b) => a.label.localeCompare(b.label));

export function getQuestionsByCategory(category: string) {
  return questions.filter((item) => item.category === category);
}
