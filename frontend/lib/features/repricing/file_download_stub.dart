/// Off the web a download has nowhere to go — the caller reports it instead.
///
/// Вікно переоцінки живе у вебі; на десктопі й Android кнопка вивантаження
/// чесно каже, що файл доступний у браузері, а не мовчить.
bool saveBytes(List<int> bytes, String filename, String mimeType) => false;
