'use strict';

const form = document.getElementById('prediction-form');
const textInput = document.getElementById('sms-text');
const tokenInput = document.getElementById('api-token');
const button = document.getElementById('submit-button');
const statusLine = document.getElementById('status');
const result = document.getElementById('result');

textInput.addEventListener('input', () => {
  document.getElementById('character-count').textContent = `${textInput.value.length} / 4096`;
});

async function checkHealth() {
  const target = document.getElementById('health');
  try {
    const response = await fetch('/health', {cache: 'no-store'});
    const data = await response.json();
    target.textContent = response.ok ? `Модель готова · ${data.model_version}` : 'Модель временно недоступна';
    target.dataset.state = response.ok ? 'success' : 'error';
  } catch {
    target.textContent = 'Нет соединения с сервисом';
    target.dataset.state = 'error';
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  statusLine.dataset.state = 'waiting';
  statusLine.textContent = 'Модель обрабатывает сообщение…';
  result.textContent = 'Ожидание ответа';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/predict', {
      method: 'POST', cache: 'no-store', signal: controller.signal,
      headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${tokenInput.value}`},
      body: JSON.stringify({text: textInput.value}),
    });
    const data = await response.json();
    if (response.ok) {
      statusLine.dataset.state = 'success';
      statusLine.textContent = data.prediction === 'spam' ? 'Спам (spam)' : 'Обычное сообщение (ham)';
    } else {
      statusLine.dataset.state = 'error';
      const descriptions = {
        400: 'Некорректный JSON.', 401: 'Нет доступа: проверьте API-токен.',
        408: 'Истекло время загрузки запроса.', 413: 'Сообщение превышает допустимый размер.',
        415: 'Неподдерживаемый формат.', 422: 'Ошибка ввода: нужен непустой текст.',
        429: 'Лимит запросов превышен. Повторите позже.',
        503: 'Модель занята или временно недоступна.', 504: 'Время предсказания превышено.',
      };
      statusLine.textContent = descriptions[response.status] || 'Не удалось выполнить запрос.';
    }
    // The API response and any untrusted value are always rendered as text.
    result.textContent = JSON.stringify(data, null, 2);
  } catch {
    statusLine.dataset.state = 'error';
    statusLine.textContent = 'Нет ответа от сервера. Проверьте соединение.';
    result.textContent = 'Запрос не завершён';
  } finally {
    clearTimeout(timer);
    button.disabled = false;
  }
});

checkHealth();
