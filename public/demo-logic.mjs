// Local heuristics choose questions; they do not infer facts or call a model.
const topics = [
  { id: 'bug', matches: /\b(bug|broken|error|crash|issue|fix|fails?|doesn.t work)\b/i,
    questions: [
      { id:'behavior', label:'What should happen, and what happens instead?', placeholder:'Expected behavior, actual behavior, and any error message…' },
      { id:'reproduction', label:'How can someone reproduce it?', placeholder:'Steps, affected page, or conditions…' }
    ] },
  { id: 'design', matches: /\b(website|webpage|page|front[ -]?end|ui|ux|design|layout|interface|visual)\b/i,
    questions: [
      { id:'focus', label:'What part should change, and what should improve?', placeholder:'For example: the dashboard layout and readability…' },
      { id:'direction', label:'Any visual direction or references?', placeholder:'Style, colors, examples, or a direction to avoid…' }
    ] },
  { id: 'performance', matches: /\b(slow|performance|speed|latency|optimi[sz]e)\b/i,
    questions: [
      { id:'bottleneck', label:'Where do you notice the slowdown?', placeholder:'Page, operation, or conditions…' },
      { id:'measure', label:'How would you measure an improvement?', placeholder:'A current measurement or target, if known…' }
    ] }
];
const general = [
  { id:'outcome', label:'What would a successful result look like?', placeholder:'Describe the behavior or outcome you want…' },
  { id:'context', label:'What context would help?', placeholder:'Relevant files, technology, or examples…' }
];
const constraints = {id:'constraints', label:'What should stay unchanged, or are there constraints?', placeholder:'Optional: functionality, scope, accessibility, deadlines…'};
export function questionsFor(prompt) {
  const topic = topics.find(item => item.matches.test(prompt));
  return [...(topic ? topic.questions : general), constraints];
}
export function buildDraft(prompt, answers = {}) {
  const original = prompt.trim();
  if (!original) return '';
  const answered = questionsFor(original).flatMap(({id,label}) => {
    const answer = typeof answers[id] === 'string' ? answers[id].trim() : '';
    return answer ? [`${label}\n${answer}`] : [];
  });
  return answered.length ? `${original}\n\nAdditional context:\n${answered.join('\n\n')}` : original;
}
