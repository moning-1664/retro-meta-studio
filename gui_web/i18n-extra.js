/* i18n.js 번역표에 더하는 문구 - 이 세션 이후에 생긴 UI(Archive/Compare/전송 모드/Storage 등). */
(function () {
  "use strict";
  const i18n = window.RMSI18n;
  if (!i18n) return;
  const wrap = i18n.setLanguage;
  // 언어를 바꾸면 열려 있는 Settings도 새 언어로 다시 그린다.
  i18n.setLanguage = function (lang) {
    const result = wrap.call(i18n, lang);
    if (typeof window.__rmsSettingsRerender === "function") window.__rmsSettingsRerender();
    return result;
  };
  i18n.addTable({
 "Archive 디렉토리": {
  "en": "Archive directory",
  "ja": "Archiveディレクトリ",
  "es": "Directorio de Archive",
  "fr": "Répertoire Archive"
 },
 "Archive 설정": {
  "en": "Archive settings",
  "ja": "Archive設定",
  "es": "Configuración de Archive",
  "fr": "Paramètres Archive"
 },
 "Archive 정리 중": {
  "en": "Cleaning up Archive",
  "ja": "Archiveを整理中",
  "es": "Limpiando Archive",
  "fr": "Nettoyage d’Archive"
 },
 "Archive에 수집": {
  "en": "Collect into Archive",
  "ja": "Archiveに収集",
  "es": "Recopilar en Archive",
  "fr": "Collecter dans Archive"
 },
 "Archive로": {
  "en": "To Archive",
  "ja": "Archiveへ",
  "es": "A Archive",
  "fr": "Vers Archive"
 },
 "Archive 디렉토리를 정하세요.": {
  "en": "Choose an Archive directory.",
  "ja": "Archiveディレクトリを指定してください。",
  "es": "Elige un directorio de Archive.",
  "fr": "Choisissez un répertoire Archive."
 },
 "Archive 디렉토리를 먼저 정하세요.": {
  "en": "Choose an Archive directory first.",
  "ja": "先にArchiveディレクトリを指定してください。",
  "es": "Elige primero un directorio de Archive.",
  "fr": "Choisissez d’abord un répertoire Archive."
 },
 "Archive 디렉토리를 정하면 사용할 수 있습니다.": {
  "en": "Available once an Archive directory is set.",
  "ja": "Archiveディレクトリを指定すると使用できます。",
  "es": "Disponible al elegir un directorio de Archive.",
  "fr": "Disponible une fois le répertoire Archive défini."
 },
 "ROM 디렉토리 (선택)": {
  "en": "ROM directory (optional)",
  "ja": "ROMディレクトリ（任意）",
  "es": "Directorio ROM (opcional)",
  "fr": "Répertoire ROM (facultatif)"
 },
 "다른 버전이 있는 것만": {
  "en": "Only items with other versions",
  "ja": "他のバージョンがあるもののみ",
  "es": "Solo con otras versiones",
  "fr": "Uniquement avec d’autres versions"
 },
 "다른 버전이 있는 항목만 보기": {
  "en": "Show only items with other versions",
  "ja": "他のバージョンがある項目のみ表示",
  "es": "Ver solo elementos con otras versiones",
  "fr": "Afficher seulement les éléments avec d’autres versions"
 },
 "이 버전을 우선 사용": {
  "en": "Prefer this version",
  "ja": "このバージョンを優先",
  "es": "Preferir esta versión",
  "fr": "Préférer cette version"
 },
 "이 버전을 우선 사용합니다.": {
  "en": "Now preferring this version.",
  "ja": "このバージョンを優先します。",
  "es": "Se prefiere esta versión.",
  "fr": "Cette version est préférée."
 },
 "우선 버전을 해제했습니다. 가장 최근 판을 씁니다.": {
  "en": "Preferred version cleared. The most recent one is used.",
  "ja": "優先バージョンを解除しました。最新版を使います。",
  "es": "Versión preferida quitada. Se usa la más reciente.",
  "fr": "Version préférée retirée. La plus récente est utilisée."
 },
 "이 판을 쓴다": {
  "en": "Use this version",
  "ja": "この版を使う",
  "es": "Usar esta versión",
  "fr": "Utiliser cette version"
 },
 "선택 해제 (가장 최근 판을 씁니다)": {
  "en": "Clear selection (use the most recent)",
  "ja": "選択解除（最新版を使用）",
  "es": "Quitar selección (usar la más reciente)",
  "fr": "Désélectionner (utiliser la plus récente)"
 },
 "(제목 없음)": {
  "en": "(No title)",
  "ja": "（タイトルなし）",
  "es": "(Sin título)",
  "fr": "(Sans titre)"
 },
 "가져오기": {
  "en": "Import",
  "ja": "インポート",
  "es": "Importar",
  "fr": "Importer"
 },
 "기기에서 찾기": {
  "en": "Find on device",
  "ja": "デバイスから検索",
  "es": "Buscar en el dispositivo",
  "fr": "Rechercher sur l’appareil"
 },
 "기기의 ES-DE 폴더를 자동으로 찾습니다.": {
  "en": "Automatically finds the ES-DE folder on the device.",
  "ja": "デバイス内のES-DEフォルダーを自動検出します。",
  "es": "Busca automáticamente la carpeta ES-DE del dispositivo.",
  "fr": "Trouve automatiquement le dossier ES-DE de l’appareil."
 },
 "Storage 옮기기": {
  "en": "Move Storage",
  "ja": "Storageを移動",
  "es": "Mover Storage",
  "fr": "Déplacer le Storage"
 },
 "System 이름 바꾸기…": {
  "en": "Rename System…",
  "ja": "System名を変更…",
  "es": "Renombrar System…",
  "fr": "Renommer le System…"
 },
 "System 이름": {
  "en": "System name",
  "ja": "System名",
  "es": "Nombre de System",
  "fr": "Nom du System"
 },
 "System 이름을 입력하세요.": {
  "en": "Enter a System name.",
  "ja": "System名を入力してください。",
  "es": "Introduce un nombre de System.",
  "fr": "Saisissez un nom de System."
 },
 "만들 위치": {
  "en": "Location to create",
  "ja": "作成場所",
  "es": "Ubicación a crear",
  "fr": "Emplacement de création"
 },
 "gamelist 만들기": {
  "en": "Create gamelist",
  "ja": "gamelistを作成",
  "es": "Crear gamelist",
  "fr": "Créer gamelist"
 },
 "Title Prefix/Postfix 일괄 적용…": {
  "en": "Apply Title Prefix/Postfix in bulk…",
  "ja": "Title Prefix/Postfixを一括適用…",
  "es": "Aplicar Prefix/Postfix de Title en lote…",
  "fr": "Appliquer Prefix/Postfix de Title en lot…"
 },
 "ROM 없는 항목 정리": {
  "en": "Clean up entries without ROM",
  "ja": "ROMのない項目を整理",
  "es": "Limpiar entradas sin ROM",
  "fr": "Nettoyer les entrées sans ROM"
 },
 "System 미디어 선택 삭제": {
  "en": "Delete selected System media",
  "ja": "System Mediaを選択削除",
  "es": "Eliminar Media seleccionado del System",
  "fr": "Supprimer les Media sélectionnés du System"
 },
 "폴더 열기 (상위 폴더)": {
  "en": "Open folder (parent)",
  "ja": "フォルダーを開く（親フォルダー）",
  "es": "Abrir carpeta (superior)",
  "fr": "Ouvrir le dossier (parent)"
 },
 "붙은 System 없음": {
  "en": "No attached System",
  "ja": "接続されたSystemなし",
  "es": "Sin System asociado",
  "fr": "Aucun System associé"
 },
 "이 Storage에 붙은 System이 없습니다.": {
  "en": "No System is attached to this Storage.",
  "ja": "このStorageに接続されたSystemはありません。",
  "es": "Ningún System está asociado a este Storage.",
  "fr": "Aucun System n’est associé à ce Storage."
 },
 "PC 경로": {
  "en": "PC path",
  "ja": "PCのパス",
  "es": "Ruta del PC",
  "fr": "Chemin du PC"
 },
 "Storage 설정을 저장했습니다.": {
  "en": "Storage settings saved.",
  "ja": "Storage設定を保存しました。",
  "es": "Configuración de Storage guardada.",
  "fr": "Paramètres du Storage enregistrés."
 },
 "Apply하면 디스크 용량을 넘습니다.": {
  "en": "Applying would exceed the disk capacity.",
  "ja": "Applyするとディスク容量を超えます。",
  "es": "Al aplicar se superaría la capacidad del disco.",
  "fr": "L’application dépasserait la capacité du disque."
 },
 "초과": {
  "en": "Over",
  "ja": "超過",
  "es": "Exceso",
  "fr": "Dépassement"
 },
 "ES-DE 기본 목록에 없음": {
  "en": "Not in the ES-DE default list",
  "ja": "ES-DE既定リストにありません",
  "es": "No está en la lista predeterminada de ES-DE",
  "fr": "Absent de la liste par défaut d’ES-DE"
 },
 "기기 경로 없음": {
  "en": "No device path",
  "ja": "デバイスのパスなし",
  "es": "Sin ruta de dispositivo",
  "fr": "Aucun chemin d’appareil"
 },
 "같은 ROM 파일": {
  "en": "Same ROM file",
  "ja": "同じROMファイル",
  "es": "Mismo archivo ROM",
  "fr": "Même fichier ROM"
 },
 "표시할 항목": {
  "en": "Items to show",
  "ja": "表示する項目",
  "es": "Elementos a mostrar",
  "fr": "Éléments à afficher"
 },
 "같은 항목": {
  "en": "Same items",
  "ja": "同じ項目",
  "es": "Elementos iguales",
  "fr": "Éléments identiques"
 },
 "있는 항목": {
  "en": "Present items",
  "ja": "ある項目",
  "es": "Elementos presentes",
  "fr": "Éléments présents"
 },
 "없는 항목": {
  "en": "Missing items",
  "ja": "ない項目",
  "es": "Elementos ausentes",
  "fr": "Éléments absents"
 },
 "상태 필터": {
  "en": "Status filter",
  "ja": "状態フィルター",
  "es": "Filtro de estado",
  "fr": "Filtre d’état"
 },
 "메타데이터가 다른 항목(≠ > <)": {
  "en": "Items with different metadata (≠ > <)",
  "ja": "メタデータが異なる項目（≠ > <）",
  "es": "Elementos con metadatos distintos (≠ > <)",
  "fr": "Éléments aux métadonnées différentes (≠ > <)"
 },
 "메타데이터는 같고 미디어만 다른 항목": {
  "en": "Same metadata, different media only",
  "ja": "メタデータは同じでMediaのみ異なる項目",
  "es": "Mismos metadatos, solo Media distinto",
  "fr": "Mêmes métadonnées, Media seulement différents"
 },
 "기준과 상대를 바꿉니다 (Swap)": {
  "en": "Swap base and other (Swap)",
  "ja": "基準と相手を入れ替えます (Swap)",
  "es": "Intercambiar base y otra (Swap)",
  "fr": "Échanger base et autre (Swap)"
 },
 "지금 상태로 다시 비교합니다 (새로고침)": {
  "en": "Compare again with the current state (Refresh)",
  "ja": "現在の状態で再比較します（更新）",
  "es": "Comparar de nuevo con el estado actual (Actualizar)",
  "fr": "Comparer à nouveau avec l’état actuel (Actualiser)"
 },
 "왼쪽": {
  "en": "Left",
  "ja": "左",
  "es": "Izquierda",
  "fr": "Gauche"
 },
 "오른쪽": {
  "en": "Right",
  "ja": "右",
  "es": "Derecha",
  "fr": "Droite"
 },
 "컬럼 표시": {
  "en": "Show columns",
  "ja": "列を表示",
  "es": "Mostrar columnas",
  "fr": "Afficher les colonnes"
 },
 "GameList 컬럼": {
  "en": "GameList columns",
  "ja": "GameList列",
  "es": "Columnas de GameList",
  "fr": "Colonnes GameList"
 },
 "기본 순서와 표시로": {
  "en": "Reset to default order and visibility",
  "ja": "既定の順序と表示に戻す",
  "es": "Restaurar orden y visibilidad predeterminados",
  "fr": "Rétablir l’ordre et l’affichage par défaut"
 },
 "머리글을 끌어 순서를 바꿉니다": {
  "en": "Drag headers to reorder",
  "ja": "見出しをドラッグして順序を変更",
  "es": "Arrastra los encabezados para reordenar",
  "fr": "Faites glisser les en-têtes pour réordonner"
 },
 "Title은 숨길 수 없습니다.": {
  "en": "Title cannot be hidden.",
  "ja": "Titleは非表示にできません。",
  "es": "Title no se puede ocultar.",
  "fr": "Title ne peut pas être masqué."
 },
 "항상 표시": {
  "en": "Always shown",
  "ja": "常に表示",
  "es": "Siempre visible",
  "fr": "Toujours affiché"
 },
 "메타데이터가 다릅니다": {
  "en": "Metadata differs",
  "ja": "メタデータが異なります",
  "es": "Los metadatos difieren",
  "fr": "Les métadonnées diffèrent"
 },
 "미디어가 다릅니다(메타데이터는 같습니다)": {
  "en": "Media differs (metadata is the same)",
  "ja": "Mediaが異なります（メタデータは同じ）",
  "es": "El Media difiere (los metadatos son iguales)",
  "fr": "Les Media diffèrent (métadonnées identiques)"
 },
 "양쪽이 같습니다": {
  "en": "Both sides are the same",
  "ja": "両側が同じです",
  "es": "Ambos lados son iguales",
  "fr": "Les deux côtés sont identiques"
 },
 "메타데이터": {
  "en": "Metadata",
  "ja": "メタデータ",
  "es": "Metadatos",
  "fr": "Métadonnées"
 },
 "ROM+메타데이터": {
  "en": "ROM + Metadata",
  "ja": "ROM+メタデータ",
  "es": "ROM + metadatos",
  "fr": "ROM + métadonnées"
 },
 "ROM 삭제": {
  "en": "Delete ROM",
  "ja": "ROMを削除",
  "es": "Eliminar ROM",
  "fr": "Supprimer la ROM"
 },
 "메타데이터 삭제(gamelist 항목)": {
  "en": "Delete metadata (gamelist entry)",
  "ja": "メタデータを削除（gamelist項目）",
  "es": "Eliminar metadatos (entrada de gamelist)",
  "fr": "Supprimer les métadonnées (entrée gamelist)"
 },
 "메타데이터 삭제": {
  "en": "Delete metadata",
  "ja": "メタデータを削除",
  "es": "Eliminar metadatos",
  "fr": "Supprimer les métadonnées"
 },
 "미디어 삭제(영상 제외)": {
  "en": "Delete media (except video)",
  "ja": "Mediaを削除（動画を除く）",
  "es": "Eliminar Media (sin vídeo)",
  "fr": "Supprimer les Media (hors vidéo)"
 },
 "영상 삭제": {
  "en": "Delete video",
  "ja": "動画を削除",
  "es": "Eliminar vídeo",
  "fr": "Supprimer la vidéo"
 },
 "일부만 있음": {
  "en": "Partially present",
  "ja": "一部のみあり",
  "es": "Presente en parte",
  "fr": "Partiellement présent"
 },
 "ROM 파일 없음 (메타데이터만 있음)": {
  "en": "No ROM file (metadata only)",
  "ja": "ROMファイルなし（メタデータのみ）",
  "es": "Sin archivo ROM (solo metadatos)",
  "fr": "Aucun fichier ROM (métadonnées seulement)"
 },
 "ROM 파일이 없는 항목입니다.": {
  "en": "This entry has no ROM file.",
  "ja": "ROMファイルのない項目です。",
  "es": "Esta entrada no tiene archivo ROM.",
  "fr": "Cette entrée n’a pas de fichier ROM."
 },
 "보낼 항목을 먼저 고르세요.": {
  "en": "Select items to send first.",
  "ja": "先に送る項目を選んでください。",
  "es": "Selecciona primero los elementos a enviar.",
  "fr": "Sélectionnez d’abord les éléments à envoyer."
 },
 "그 탭에서 Apply하세요.": {
  "en": "Apply from that tab.",
  "ja": "そのタブでApplyしてください。",
  "es": "Aplica desde esa pestaña.",
  "fr": "Appliquez depuis cet onglet."
 },
 "Compare Mode가 아닙니다.": {
  "en": "Not in Compare Mode.",
  "ja": "Compare Modeではありません。",
  "es": "No está en Compare Mode.",
  "fr": "Pas en Compare Mode."
 },
 "미디어 복사": {
  "en": "Copy media",
  "ja": "Mediaをコピー",
  "es": "Copiar Media",
  "fr": "Copier les Media"
 },
 "미디어 붙여넣기": {
  "en": "Paste media",
  "ja": "Mediaを貼り付け",
  "es": "Pegar Media",
  "fr": "Coller les Media"
 },
 "복사한 미디어가 없습니다": {
  "en": "No media copied",
  "ja": "コピーしたMediaがありません",
  "es": "No hay Media copiado",
  "fr": "Aucun Media copié"
 },
 "붙여넣을 System 고르기": {
  "en": "Choose a System to paste into",
  "ja": "貼り付け先のSystemを選択",
  "es": "Elegir System donde pegar",
  "fr": "Choisir le System de destination"
 },
 "붙여넣을 새 내용이 없습니다(전부 이미 있음).": {
  "en": "Nothing new to paste (everything already exists).",
  "ja": "貼り付ける新しい内容はありません（すべて既存）。",
  "es": "No hay nada nuevo que pegar (ya existe todo).",
  "fr": "Rien de nouveau à coller (tout existe déjà)."
 },
 "보완 - 없는 것만 채웁니다": {
  "en": "Patch - fill only what is missing",
  "ja": "補完 - 足りないものだけ補います",
  "es": "Completar - solo rellena lo que falta",
  "fr": "Compléter - remplit seulement ce qui manque"
 },
 "덮어쓰기 - 원본의 값을 적용합니다": {
  "en": "Overwrite - apply the source values",
  "ja": "上書き - 元の値を適用します",
  "es": "Sobrescribir - aplica los valores del origen",
  "fr": "Écraser - applique les valeurs de la source"
 },
 "완전 교체 - 원본으로 다시 만듭니다": {
  "en": "Replace - rebuild from the source",
  "ja": "完全置換 - 元から作り直します",
  "es": "Reemplazo total - reconstruye desde el origen",
  "fr": "Remplacement total - reconstruit depuis la source"
 },
 "붙여넣기 모드 - 다음 Ctrl+V부터 적용됩니다": {
  "en": "Paste mode - applies from the next Ctrl+V",
  "ja": "貼り付けモード - 次のCtrl+Vから適用",
  "es": "Modo de pegado - se aplica desde el próximo Ctrl+V",
  "fr": "Mode de collage - appliqué dès le prochain Ctrl+V"
 },
 "붙여넣기 모드": {
  "en": "Paste mode",
  "ja": "貼り付けモード",
  "es": "Modo de pegado",
  "fr": "Mode de collage"
 },
 "ROM도 교체": {
  "en": "Replace ROM too",
  "ja": "ROMも置換",
  "es": "Reemplazar también la ROM",
  "fr": "Remplacer aussi la ROM"
 },
 "ROM 파일 복사": {
  "en": "Copy ROM file",
  "ja": "ROMファイルをコピー",
  "es": "Copiar archivo ROM",
  "fr": "Copier le fichier ROM"
 },
 "충돌을 먼저 해결해야 적용할 수 있습니다": {
  "en": "Resolve conflicts before applying",
  "ja": "適用する前に競合を解決してください",
  "es": "Resuelve los conflictos antes de aplicar",
  "fr": "Résolvez les conflits avant d’appliquer"
 },
 "적용 완료": {
  "en": "Applied",
  "ja": "適用完了",
  "es": "Aplicado",
  "fr": "Appliqué"
 },
 "완료": {
  "en": "Done",
  "ja": "完了",
  "es": "Hecho",
  "fr": "Terminé"
 },
 "준비 중": {
  "en": "Coming soon",
  "ja": "準備中",
  "es": "Próximamente",
  "fr": "Bientôt disponible"
 },
 "기타": {
  "en": "Other",
  "ja": "その他",
  "es": "Otros",
  "fr": "Autres"
 },
 "이름 없음": {
  "en": "Unnamed",
  "ja": "名前なし",
  "es": "Sin nombre",
  "fr": "Sans nom"
 },
 "음량": {
  "en": "Volume",
  "ja": "音量",
  "es": "Volumen",
  "fr": "Volume"
 },
 "소리를 켰을 때의 재생 음량입니다.": {
  "en": "Playback volume when sound is on.",
  "ja": "音声オン時の再生音量です。",
  "es": "Volumen de reproducción con el sonido activado.",
  "fr": "Volume de lecture lorsque le son est activé."
 },
 "미디어": {
  "en": "Media",
  "ja": "Media",
  "es": "Media",
  "fr": "Media"
 },
 "영상": {
  "en": "Video",
  "ja": "動画",
  "es": "Vídeo",
  "fr": "Vidéo"
 },
 "제목": {
  "en": "Title",
  "ja": "タイトル",
  "es": "Título",
  "fr": "Titre"
 },
 "제목 앞에 (Prefix)": {
  "en": "Before the title (Prefix)",
  "ja": "タイトルの前 (Prefix)",
  "es": "Antes del título (Prefix)",
  "fr": "Avant le titre (Prefix)"
 },
 "제목 뒤에 (Postfix)": {
  "en": "After the title (Postfix)",
  "ja": "タイトルの後 (Postfix)",
  "es": "Después del título (Postfix)",
  "fr": "Après le titre (Postfix)"
 },
 "한국(KR)": {
  "en": "Korea (KR)",
  "ja": "韓国 (KR)",
  "es": "Corea (KR)",
  "fr": "Corée (KR)"
 },
 "Dashboard를 불러오는 중…": {
  "en": "Loading Dashboard…",
  "ja": "Dashboardを読み込み中…",
  "es": "Cargando Dashboard…",
  "fr": "Chargement du Dashboard…"
 },
 "Dashboard 데이터를 읽지 못했습니다.": {
  "en": "Could not read Dashboard data.",
  "ja": "Dashboardデータを読み込めませんでした。",
  "es": "No se pudieron leer los datos del Dashboard.",
  "fr": "Impossible de lire les données du Dashboard."
 },
 "Media 파일이 없습니다.": {
  "en": "There is no Media file.",
  "ja": "Mediaファイルがありません。",
  "es": "No hay archivo Media.",
  "fr": "Aucun fichier Media."
 },
 "Storage를 찾을 수 없습니다.": {
  "en": "Storage not found.",
  "ja": "Storageが見つかりません。",
  "es": "No se encontró el Storage.",
  "fr": "Storage introuvable."
 },
 "게임이 있는 System은 삭제할 수 없습니다.": {
  "en": "A System that has games cannot be deleted.",
  "ja": "ゲームがあるSystemは削除できません。",
  "es": "No se puede eliminar un System con juegos.",
  "fr": "Un System contenant des jeux ne peut pas être supprimé."
 },
 "등록 목록에서만 제거합니다. 실제 파일은 그대로입니다.": {
  "en": "Removes it from the list only. Actual files stay as they are.",
  "ja": "登録リストからのみ削除します。実ファイルはそのままです。",
  "es": "Solo se quita de la lista. Los archivos reales no cambian.",
  "fr": "Retiré de la liste uniquement. Les fichiers restent intacts."
 },
 "기준": {
  "en": "Base",
  "ja": "基準",
  "es": "Base",
  "fr": "Base"
 },
 "기준 해제": {
  "en": "Clear base",
  "ja": "基準を解除",
  "es": "Quitar base",
  "fr": "Retirer la base"
 },
 "Compare 기준으로 지정": {
  "en": "Set as Compare base",
  "ja": "Compareの基準に指定",
  "es": "Establecer como base de Compare",
  "fr": "Définir comme base de Compare"
 },
 "비교 기준을 해제했습니다.": {
  "en": "Compare base cleared.",
  "ja": "比較の基準を解除しました。",
  "es": "Base de comparación quitada.",
  "fr": "Base de comparaison retirée."
 },
 "후보를 찾지 못했습니다.": {
  "en": "No candidates found.",
  "ja": "候補が見つかりませんでした。",
  "es": "No se encontraron candidatos.",
  "fr": "Aucun candidat trouvé."
 },
 "Match를 해제했습니다.": {
  "en": "Match cleared.",
  "ja": "Matchを解除しました。",
  "es": "Match quitado.",
  "fr": "Match retiré."
 },
 "선택 해제": {
  "en": "Clear selection",
  "ja": "選択解除",
  "es": "Quitar selección",
  "fr": "Désélectionner"
 },
 "설명": {
  "en": "Description",
  "ja": "説明",
  "es": "Descripción",
  "fr": "Description"
 },
 "설명이 여기에 표시됩니다.": {
  "en": "The description appears here.",
  "ja": "説明がここに表示されます。",
  "es": "La descripción aparece aquí.",
  "fr": "La description s’affiche ici."
 },
 "수집할 항목이 없습니다.": {
  "en": "Nothing to collect.",
  "ja": "収集する項目がありません。",
  "es": "No hay nada que recopilar.",
  "fr": "Rien à collecter."
 }
});
})();
