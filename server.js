const express = require('express');
const { Pool } = require('pg');
const cors = require('cors');
const path = require('path');
const fs = require('fs').promises;
require('dotenv').config();

const app = express();

app.use(cors({
  origin: ['http://localhost:3000', 'http://localhost:3001', 'http://127.0.0.1:3001'],
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
  credentials: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

const pool = new Pool({
  user: process.env.DB_USER,
  host: process.env.DB_HOST,
  database: process.env.DB_NAME,
  password: process.env.DB_PASSWORD,
  port: process.env.DB_PORT ? parseInt(process.env.DB_PORT, 10) : 5432,
});

pool.connect((err, client, release) => {
  if (err) {
    console.error('Ошибка подключения к базе данных:', err.stack);
    process.exit(1);
  }
  console.log('Успешное подключение к PostgreSQL');
  release();
});

// Получение списка инцидентов
app.get('/api/incidents', async (req, res) => {
  try {
    const {
      page = 1,
      limit = 5,
      search = '',
      sort = 'discovery_date',
      order = 'desc',
      type = '',
      status = ''
    } = req.query;

    const pageInt = parseInt(page, 10);
    const limitInt = parseInt(limit, 10);
    const offset = (pageInt - 1) * limitInt;

    const sortClean = String(sort).trim().toLowerCase();
    const validSortFields = ['id', 'type', 'source', 'discovery_date', 'status', 'company_name'];
    const sortField = validSortFields.includes(sortClean) ? sortClean : 'discovery_date';
    const sortOrder = order.toUpperCase() === 'ASC' ? 'ASC' : 'DESC';

    const conditions = [];
    const params = [];
    let paramIdx = 1;

    if (search) {
      conditions.push(`(type ILIKE $${paramIdx} OR source ILIKE $${paramIdx} OR company_name ILIKE $${paramIdx})`);
      params.push(`%${search}%`);
      paramIdx++;
    }
    if (type) {
      conditions.push(`type = $${paramIdx}`);
      params.push(type);
      paramIdx++;
    }
    if (status) {
      conditions.push(`status = $${paramIdx}`);
      params.push(status);
      paramIdx++;
    }

    const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';

    const query = `
      SELECT
        id,
        company_name,
        type,
        source,
        discovery_date,
        status
      FROM incidents
      ${whereClause}
      ORDER BY ${sortField} ${sortOrder}
      LIMIT $${paramIdx} OFFSET $${paramIdx + 1}
    `;

    params.push(limitInt, offset);

    const countQuery = `
      SELECT COUNT(*) 
      FROM incidents
      ${whereClause}
    `;

    const countParams = params.slice(0, paramIdx - 1);

    const [incidentsResult, countResult] = await Promise.all([
      pool.query(query, params),
      pool.query(countQuery, countParams)
    ]);

    const totalCount = parseInt(countResult.rows[0].count, 10);
    const totalPages = Math.ceil(totalCount / limitInt);

    res.json({
      data: incidentsResult.rows,
      pagination: {
        total: totalCount,
        page: pageInt,
        limit: limitInt,
        totalPages,
      },
    });

  } catch (err) {
    console.error('Ошибка при получении инцидентов:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});

// Получение подробностей инцидента по ID с рекомендациями
app.get('/api/incidents/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const incidentId = parseInt(id, 10);
    if (isNaN(incidentId)) {
      return res.status(400).json({ error: 'Некорректный ID инцидента' });
    }

    // Получаем сам инцидент
    const incidentQuery = `
      SELECT
        id,
        company_name,
        type,
        source,
        discovery_date,
        status,
        description
      FROM incidents
      WHERE id = $1
    `;
    const incidentResult = await pool.query(incidentQuery, [incidentId]);

    if (incidentResult.rows.length === 0) {
      return res.status(404).json({ error: 'Инцидент не найден' });
    }

    const incident = incidentResult.rows[0];

    // Получаем рекомендации по типу утечки
    const recQuery = `
      SELECT audience, recommendation
      FROM risk_recommendations
      WHERE leak_type = $1
    `;
    const recResult = await pool.query(recQuery, [incident.type]);

    // Формируем объект с рекомендациями по аудиториям
    const recommendations = {
      'Базовый': [],
      'ИБ': []
    };

    recResult.rows.forEach(row => {
      if (recommendations[row.audience]) {
        recommendations[row.audience].push(row.recommendation);
      }
    });

    // Отдаем подробности + рекомендации
    res.json({
      ...incident,
      recommendations
    });

  } catch (err) {
    console.error('Ошибка при получении подробностей инцидента:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});


// Добавление инцидента
app.post('/api/incidents', async (req, res) => {
  try {
    const {
      company_name,
      type,
      source,
      discovery_date,
      status = 'Новый',
      description = null
    } = req.body;

    if (!company_name?.trim() || !type?.trim() || !source?.trim() || !discovery_date) {
      return res.status(400).json({ error: 'Заполните все обязательные поля' });
    }

    const parsedDate = new Date(discovery_date);
    if (isNaN(parsedDate.getTime())) {
      return res.status(400).json({ error: 'Некорректный формат discovery_date' });
    }

    const insertQuery = `
      INSERT INTO incidents (company_name, type, source, discovery_date, status, description, created_at, updated_at)
      VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
      RETURNING id, company_name, type, source, to_char(discovery_date, 'DD.MM.YYYY HH24:MI') AS discovery_date, status, description
    `;
    const values = [company_name.trim(), type.trim(), source.trim(), parsedDate, status, description];
    const result = await pool.query(insertQuery, values);

    res.status(201).json(result.rows[0]);

  } catch (err) {
    console.error('Ошибка при добавлении инцидента:', err);
    res.status(500).json({ error: `Внутренняя ошибка сервера: ${err.message}` });
  }
});

// Остальные маршруты
app.get('/api/stats', async (req, res) => {
  try {
    const queries = [
      pool.query("SELECT COUNT(*) FROM incidents WHERE discovery_date::date = CURRENT_DATE"),
      pool.query("SELECT COUNT(*) FROM incidents WHERE status = 'Средний'"),
      pool.query("SELECT COUNT(*) FROM incidents WHERE status = 'Критический'"),
      pool.query("SELECT COUNT(*) FROM incidents WHERE discovery_date >= date_trunc('month', CURRENT_DATE)")
    ];

    const [todayRes, mediumRes, criticalRes, monthRes] = await Promise.all(queries);

    res.json({
      today: parseInt(todayRes.rows[0].count, 10),
      processing: parseInt(mediumRes.rows[0].count, 10),
      critical: parseInt(criticalRes.rows[0].count, 10),
      month: parseInt(monthRes.rows[0].count, 10)
    });

  } catch (err) {
    console.error('Ошибка при получении статистики:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});

app.get('/api/activity', async (req, res) => {
  try {
    const { period = 'week' } = req.query;
    let interval, groupBy;

    switch (period) {
      case 'day':
        interval = '1 day';
        groupBy = "date_trunc('hour', discovery_date)";
        break;
      case 'month':
        interval = '1 month';
        groupBy = "date_trunc('day', discovery_date)";
        break;
      case 'year':
        interval = '1 year';
        groupBy = "date_trunc('month', discovery_date)";
        break;
      default:
        interval = '1 week';
        groupBy = "date_trunc('day', discovery_date)";
    }

    const query = `
      SELECT 
        ${groupBy} AS date,
        COUNT(*)::int AS count
      FROM incidents
      WHERE discovery_date >= NOW() - INTERVAL '${interval}'
      GROUP BY date
      ORDER BY date
    `;

    const result = await pool.query(query);
    res.json(result.rows.map(row => ({
      date: row.date.toISOString(),
      count: row.count
    })));

  } catch (err) {
    console.error('Ошибка при получении данных активности:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});

app.get('/api/leak-types', async (req, res) => {
  try {
    const query = `
      SELECT 
        type,
        COUNT(*)::int AS count
      FROM incidents
      GROUP BY type
      ORDER BY count DESC
    `;

    const result = await pool.query(query);
    res.json(result.rows);

  } catch (err) {
    console.error('Ошибка при получении типов утечек:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});

// Настройки (получение и сохранение)
app.get('/api/settings', async (req, res) => {
  try {
    const query = 'SELECT frequency, modules FROM settings ORDER BY updated_at DESC LIMIT 1';
    const result = await pool.query(query);
    if (result.rows.length === 0) {
      return res.json({ frequency: 'daily', modules: [] });
    }
    res.json(result.rows[0]);
  } catch (err) {
    console.error('Ошибка при получении настроек:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});

app.post('/api/settings', async (req, res) => {
  try {
    const { frequency, modules } = req.body;
    if (!frequency || !['hourly', 'daily', 'weekly'].includes(frequency)) {
      return res.status(400).json({ error: 'Некорректная частота сканирования' });
    }
    if (!Array.isArray(modules) || !modules.every(m => ['webparser', 'GitHubparser', 'pastebinparser', 'telegramparser'].includes(m))) {
      return res.status(400).json({ error: 'Некорректный список модулей' });
    }

    const query = `
      INSERT INTO settings (frequency, modules, updated_at)
      VALUES ($1, $2, NOW())
      ON CONFLICT (id)
      DO UPDATE SET frequency = $1, modules = $2, updated_at = NOW()
      RETURNING frequency, modules
    `;
    const values = [frequency, JSON.stringify(modules)];
    const result = await pool.query(query, values);

    const config = { frequency, modules };
    await fs.writeFile(path.join(__dirname, 'config.json'), JSON.stringify(config, null, 2));

    res.json(result.rows[0]);
  } catch (err) {
    console.error('Ошибка при сохранении настроек:', err);
    res.status(500).json({ error: 'Внутренняя ошибка сервера' });
  }
});

// 404 и глобальные ошибки
app.use((req, res) => {
  res.status(404).json({ error: 'Ресурс не найден' });
});

app.use((err, req, res, next) => {
  console.error('Ошибка сервера:', err.stack);
  res.status(500).json({ error: 'Внутренняя ошибка сервера' });
});

// Запуск сервера
const PORT = process.env.PORT || 3001;
const server = app.listen(PORT, () => {
  console.log(`Сервер запущен на порту ${PORT}`);
});

const shutdown = async () => {
  console.log('Завершение работы сервера...');
  try {
    await pool.end();
    console.log('Пул подключений к PostgreSQL закрыт');
    server.close(() => {
      console.log('HTTP сервер закрыт');
      process.exit(0);
    });
    setTimeout(() => {
      console.error('Таймаут завершения работы');
      process.exit(1);
    }, 5000);
  } catch (err) {
    console.error('Ошибка при завершении работы:', err);
    process.exit(1);
  }
};

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);