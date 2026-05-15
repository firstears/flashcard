const { Client } = require('@notionhq/client');
const fs = require('fs');

const notion = new Client({ auth: process.env.NOTION_TOKEN });
const DATABASE_ID = 'bbe9625bc08146d5b6abc16f196a0b52';

async function main() {
  const response = await notion.databases.query({
    database_id: DATABASE_ID,
    sorts: [{ property: '상태', direction: 'ascending' }],
  });

  const statusMap = {
    '복습 필요': 'hard',
    '애매': 'ok',
    '암기 완료': 'done',
    '신규': 'new',
  };

  const cards = response.results.map(page => {
    const p = page.properties;
    return {
      word: p['단어']?.title?.[0]?.plain_text || '',
      phonetic: p['발음기호']?.rich_text?.[0]?.plain_text || '',
      status: statusMap[p['상태']?.select?.name] || 'new',
      pos: p['품사']?.rich_text?.[0]?.plain_text || '',
      vtype: p['자타동사']?.select?.name || null,
      def: p['한글뜻']?.rich_text?.[0]?.plain_text || '',
      enDef: p['영어정의']?.rich_text?.[0]?.plain_text || '',
      ex: (p['예문']?.rich_text?.[0]?.plain_text || '') + '\n' + (p['예문번역']?.rich_text?.[0]?.plain_text || ''),
    };
  }).filter(c => c.word);

  const output = `const cards = ${JSON.stringify(cards, null, 2)};\n`;
  fs.writeFileSync('data.js', output);
  console.log(`Generated ${cards.length} cards.`);
}

main().catch(console.error);
