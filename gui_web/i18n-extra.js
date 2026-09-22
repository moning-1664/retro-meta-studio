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
 },
 "충돌 해결 - 쓰기 막힘": {
  "en": "Write blocked - resolve conflict",
  "ja": "書き込みがブロックされています - 競合を解決",
  "es": "Escritura bloqueada - resolver conflicto",
  "fr": "Écriture bloquée - résoudre le conflit"
 },
 "기기 Collection은 Metadata만 다룹니다. 파일 작업은 ADB 모드에서 지원할 예정입니다.": {
  "en": "Device Collections only handle Metadata. File operations will be supported in ADB mode.",
  "ja": "デバイスCollectionはMetadataのみ扱います。ファイル操作はADBモードで対応予定です。",
  "es": "Las Collections de dispositivo solo gestionan Metadata. Las operaciones de archivo se admitirán en modo ADB.",
  "fr": "Les Collections d'appareil ne gèrent que les Metadata. Les opérations sur fichiers seront prises en charge en mode ADB."
 },
 "ROM·gamelist·media 폴더 이름을 함께 바꿉니다.": {
  "en": "Renames the ROM, gamelist and media folders together.",
  "ja": "ROM・gamelist・media フォルダーの名前をまとめて変更します。",
  "es": "Renombra juntas las carpetas de ROM, gamelist y media.",
  "fr": "Renomme ensemble les dossiers ROM, gamelist et media."
 },
 "이 System에 gamelist가 없으면 ROM 파일명만 담아 만듭니다.": {
  "en": "If this System has no gamelist, creates one containing only ROM filenames.",
  "ja": "このSystemにgamelistがなければ、ROMファイル名だけを入れて作成します。",
  "es": "Si este System no tiene gamelist, crea uno que contiene solo los nombres de archivo ROM.",
  "fr": "Si ce System n'a pas de gamelist, en crée un contenant uniquement les noms de fichiers ROM."
 },
 "지금 설정으로는 이 System에서 바뀔 제목이 없습니다. Settings > Metadata & Media에서 규칙을 확인하세요.": {
  "en": "With the current settings, no titles in this System would change. Check the rule in Settings > Metadata & Media.",
  "ja": "現在の設定では、このSystemで変わるタイトルはありません。Settings > Metadata & Mediaでルールを確認してください。",
  "es": "Con la configuración actual, ningún título de este System cambiaría. Revisa la regla en Settings > Metadata & Media.",
  "fr": "Avec les réglages actuels, aucun titre de ce System ne changerait. Vérifiez la règle dans Settings > Metadata & Media."
 },
 "이 System 전체 제목에서 기존 장식을 떼고, Settings에 설정한 지역별 표시를 다시 붙입니다.": {
  "en": "Strips the existing decoration from every title in this System, then reapplies the region markers set in Settings.",
  "ja": "このSystemの全タイトルから既存の装飾を外し、Settingsで設定した地域別表示を付け直します。",
  "es": "Quita la decoración existente de todos los títulos de este System y vuelve a aplicar las marcas de región definidas en Settings.",
  "fr": "Retire la décoration existante de tous les titres de ce System, puis réapplique les marqueurs de région définis dans Settings."
 },
 "Metadata/Media는 있는데 ROM 파일이 없는 항목을 찾아 지웁니다.": {
  "en": "Finds and deletes entries that have Metadata/Media but no ROM file.",
  "ja": "MetadataやMediaはあるがROMファイルがない項目を探して削除します。",
  "es": "Busca y elimina las entradas que tienen Metadata/Media pero no archivo ROM.",
  "fr": "Recherche et supprime les entrées ayant des Metadata/Media mais pas de fichier ROM."
 },
 "Cover/Screenshot/Video 등 media 종류를 골라 이 System 전체에서 지웁니다.": {
  "en": "Choose media types such as Cover/Screenshot/Video and delete them across this entire System.",
  "ja": "Cover/Screenshot/Videoなどmediaの種類を選び、このSystem全体から削除します。",
  "es": "Elige tipos de media como Cover/Screenshot/Video y elimínalos en todo este System.",
  "fr": "Choisissez des types de Media comme Cover/Screenshot/Video et supprimez-les dans tout ce System."
 },
 "이 System의 ROM·Metadata·Media를 디스크에서 지우고 목록에서 뺍니다.": {
  "en": "Deletes this System's ROM, Metadata and Media from disk and removes it from the list.",
  "ja": "このSystemのROM・Metadata・Mediaをディスクから削除し、一覧から外します。",
  "es": "Elimina el ROM, Metadata y Media de este System del disco y lo quita de la lista.",
  "fr": "Supprime le ROM, les Metadata et les Media de ce System du disque et le retire de la liste."
 },
 "저장 형식": {
  "en": "Storage format",
  "ja": "保存形式",
  "es": "Formato de almacenamiento",
  "fr": "Format de stockage"
 },
 "Archive를 어떤 Frontend의 형식으로 둘지 정합니다. 바꾸면 그 형식으로 다시 배치합니다(이전 형식의 파일은 지우지 않습니다).": {
  "en": "Decides which Frontend's format the Archive is kept in. Changing it reorganizes into that format (files from the previous format are not deleted).",
  "ja": "Archiveをどのフロントエンドの形式で保存するか決めます。変更するとその形式で再配置します(以前の形式のファイルは削除しません)。",
  "es": "Decide en qué formato de Frontend se guarda el Archive. Cambiarlo lo reorganiza en ese formato (no se eliminan los archivos del formato anterior).",
  "fr": "Détermine dans quel format de Frontend l'Archive est conservée. Le changer la réorganise dans ce format (les fichiers de l'ancien format ne sont pas supprimés)."
 },
 "메타데이터(gamelist)와 미디어가 저장될 폴더입니다. 이전에 만든 Archive 폴더를 고르면 그 내용을 읽어 옵니다.": {
  "en": "The folder where metadata (gamelist) and media will be stored. Choosing a previously created Archive folder reads its existing content.",
  "ja": "メタデータ(gamelist)とMediaが保存されるフォルダーです。以前作成したArchiveフォルダーを選ぶと、その内容を読み込みます。",
  "es": "La carpeta donde se guardarán los metadatos (gamelist) y el Media. Si eliges una carpeta de Archive creada antes, se lee su contenido.",
  "fr": "Le dossier où les métadonnées (gamelist) et les Media seront stockés. Choisir un dossier Archive déjà créé en lit le contenu existant."
 },
 "ROM을 둘 폴더입니다. 지정하면 여기에 ROM을 넣고 새로고침해서 Archive에 올릴 수 있고, Collection으로 ROM까지 보낼 수 있습니다.": {
  "en": "The folder where ROMs will be kept. If set, you can place ROMs here and refresh to bring them into the Archive, and send ROMs along when sending to a Collection.",
  "ja": "ROMを置くフォルダーです。指定すると、ここにROMを置いて更新することでArchiveに取り込め、CollectionへROMまで送ることができます。",
  "es": "La carpeta donde se guardarán las ROM. Si se indica, puedes colocar ROM aquí y actualizar para incorporarlas al Archive, y enviar también las ROM a una Collection.",
  "fr": "Le dossier où seront placées les ROM. S'il est défini, vous pouvez y placer des ROM et actualiser pour les intégrer à l'Archive, et envoyer aussi les ROM vers une Collection."
 },
 "미디어를 Archive에 보관": {
  "en": "Keep media in the Archive",
  "ja": "MediaをArchiveに保管",
  "es": "Guardar Media en el Archive",
  "fr": "Conserver les Media dans l'Archive"
 },
 "켜면 미디어 파일을 Archive 디렉토리로 복사해 둡니다(없는 파일만 복사). 끄면 원본 Collection의 파일을 참조만 합니다.": {
  "en": "When on, media files are copied into the Archive directory (only missing files are copied). When off, the original Collection's files are only referenced.",
  "ja": "オンにするとMediaファイルをArchiveディレクトリにコピーします(ないファイルのみコピー)。オフにすると元のCollectionのファイルを参照するだけです。",
  "es": "Si está activado, los archivos de Media se copian al directorio de Archive (solo se copian los que faltan). Si está desactivado, solo se referencian los archivos de la Collection original.",
  "fr": "Si activé, les fichiers Media sont copiés dans le répertoire Archive (seuls les fichiers manquants sont copiés). Si désactivé, seuls les fichiers de la Collection d'origine sont référencés."
 },
 "저장하고 적용": {
  "en": "Save and apply",
  "ja": "保存して適用",
  "es": "Guardar y aplicar",
  "fr": "Enregistrer et appliquer"
 },
 "예: D:\\Archives": {
  "en": "e.g. D:\\Archives",
  "ja": "例: D:\\Archives",
  "es": "p. ej. D:\\Archives",
  "fr": "ex. D:\\Archives"
 },
 "비워 두면 Archive 디렉토리 안에 둡니다": {
  "en": "Leave empty to keep it inside the Archive directory",
  "ja": "空欄の場合はArchiveディレクトリの中に置きます",
  "es": "Déjalo vacío para mantenerlo dentro del directorio de Archive",
  "fr": "Laissez vide pour le conserver dans le répertoire Archive"
 },
 "No.는 항상 맨 앞입니다": {
  "en": "No. is always first",
  "ja": "No.は常に先頭です",
  "es": "No. siempre va primero",
  "fr": "No. est toujours en premier"
 },
 "끌어서 순서 바꾸기 (↑↓ 키도 됩니다)": {
  "en": "Drag to reorder (arrow keys also work)",
  "ja": "ドラッグして順序を変更(↑↓キーも使えます)",
  "es": "Arrastra para reordenar (las flechas también funcionan)",
  "fr": "Glissez pour réordonner (les flèches fonctionnent aussi)"
 },
 "항상 맨 앞": {
  "en": "Always first",
  "ja": "常に先頭",
  "es": "Siempre primero",
  "fr": "Toujours en premier"
 },
 "기본값으로": {
  "en": "Reset to default",
  "ja": "既定値に戻す",
  "es": "Restaurar valor predeterminado",
  "fr": "Rétablir la valeur par défaut"
 },
 "☰를 끌어 순서를 바꿉니다. 목록 머리글을 끌거나 우클릭해도 됩니다.": {
  "en": "Drag ☰ to reorder. You can also drag or right-click the list header.",
  "ja": "☰をドラッグして順序を変更できます。一覧の見出しをドラッグまたは右クリックしても構いません。",
  "es": "Arrastra ☰ para reordenar. También puedes arrastrar o hacer clic derecho en el encabezado de la lista.",
  "fr": "Faites glisser ☰ pour réordonner. Vous pouvez aussi glisser ou faire un clic droit sur l'en-tête de la liste."
 },
 "여러 Collection에서 수집한 Metadata 보관소": {
  "en": "A repository of Metadata collected from multiple Collections",
  "ja": "複数のCollectionから収集したMetadataの保管庫",
  "es": "Un repositorio de Metadata recopilado de varias Collections",
  "fr": "Un dépôt de Metadata collecté depuis plusieurs Collections"
 },
 "떼어 낸 창에는 Collection을 하나만 열 수 있습니다. 메인 창에서 여세요.": {
  "en": "A detached window can hold only one Collection. Open it from the main window.",
  "ja": "切り離したウィンドウにはCollectionを1つしか開けません。メインウィンドウで開いてください。",
  "es": "Una ventana separada solo puede tener una Collection abierta. Ábrela desde la ventana principal.",
  "fr": "Une fenêtre détachée ne peut contenir qu'une seule Collection. Ouvrez-la depuis la fenêtre principale."
 },
 "등록된 Collection이 없습니다.": {
  "en": "No Collection is registered.",
  "ja": "登録されたCollectionはありません。",
  "es": "No hay ninguna Collection registrada.",
  "fr": "Aucune Collection n'est enregistrée."
 },
 "예: Android ES-DE": {
  "en": "e.g. Android ES-DE",
  "ja": "例: Android ES-DE",
  "es": "p. ej. Android ES-DE",
  "fr": "ex. Android ES-DE"
 },
 "External ROM 디렉토리": {
  "en": "External ROM directory",
  "ja": "外部ROMディレクトリ",
  "es": "Directorio ROM externo",
  "fr": "Répertoire ROM externe"
 },
 "(선택)": {
  "en": "(optional)",
  "ja": "(任意)",
  "es": "(opcional)",
  "fr": "(facultatif)"
 },
 "ES-DE의 gamelists와 downloaded_media가 포함된 디렉토리입니다.": {
  "en": "The directory containing ES-DE's gamelists and downloaded_media.",
  "ja": "ES-DEのgamelistsとdownloaded_mediaが含まれるディレクトリです。",
  "es": "El directorio que contiene gamelists y downloaded_media de ES-DE.",
  "fr": "Le répertoire contenant les gamelists et downloaded_media d'ES-DE."
 },
 "ROM(과 메타데이터)이 들어 있는 디렉토리입니다.": {
  "en": "The directory containing the ROM (and metadata).",
  "ja": "ROM(とメタデータ)が入っているディレクトリです。",
  "es": "El directorio que contiene la ROM (y los metadatos).",
  "fr": "Le répertoire contenant la ROM (et les métadonnées)."
 },
 "ROM이 System별 폴더로 들어 있는 디렉토리입니다.": {
  "en": "The directory whose ROMs are organized into per-System folders.",
  "ja": "ROMがSystemごとのフォルダーに入っているディレクトリです。",
  "es": "El directorio cuyas ROM están organizadas en carpetas por System.",
  "fr": "Le répertoire dont les ROM sont organisées en dossiers par System."
 },
 "Metadata 디렉토리와 ROM 디렉토리 중 하나는 선택하세요.": {
  "en": "Choose either the Metadata directory or the ROM directory.",
  "ja": "MetadataディレクトリかROMディレクトリのどちらかを選択してください。",
  "es": "Elige el directorio de Metadata o el directorio ROM.",
  "fr": "Choisissez le répertoire de Metadata ou le répertoire ROM."
 },
 "등록된 Collection이 없습니다. 상단의 \"+\"를 눌러 추가하세요.": {
  "en": "No Collection is registered. Click \"+\" at the top to add one.",
  "ja": "登録されたCollectionはありません。上部の「+」を押して追加してください。",
  "es": "No hay ninguna Collection registrada. Pulsa \"+\" arriba para añadir una.",
  "fr": "Aucune Collection n'est enregistrée. Cliquez sur « + » en haut pour en ajouter une."
 },
 "(하위 폴더가 없습니다)": {
  "en": "(No subfolders)",
  "ja": "(サブフォルダーがありません)",
  "es": "(Sin subcarpetas)",
  "fr": "(Aucun sous-dossier)"
 },
 "ES-DE 폴더를 찾았습니다. 다르면 '찾아보기'로 고르세요.": {
  "en": "Found the ES-DE folder. If it's wrong, pick one with 'Browse'.",
  "ja": "ES-DEフォルダーが見つかりました。違う場合は「参照」で選んでください。",
  "es": "Se encontró la carpeta ES-DE. Si no es la correcta, elígela con \"Examinar\".",
  "fr": "Dossier ES-DE trouvé. S'il est incorrect, choisissez-en un avec « Parcourir »."
 },
 "ES-DE 폴더를 못 찾았습니다. '찾아보기'로 직접 고르세요.": {
  "en": "Could not find the ES-DE folder. Pick one directly with 'Browse'.",
  "ja": "ES-DEフォルダーが見つかりませんでした。「参照」で直接選んでください。",
  "es": "No se pudo encontrar la carpeta ES-DE. Elígela directamente con \"Examinar\".",
  "fr": "Impossible de trouver le dossier ES-DE. Choisissez-en un directement avec « Parcourir »."
 },
 "연결된 기기가 없습니다. USB를 파일 전송(MTP) 모드로 두고 기기 화면에서 허용을 눌러주세요.": {
  "en": "No device is connected. Set USB to file transfer (MTP) mode and tap Allow on the device screen.",
  "ja": "接続されたデバイスがありません。USBをファイル転送(MTP)モードにし、デバイス画面で許可を押してください。",
  "es": "No hay ningún dispositivo conectado. Pon el USB en modo transferencia de archivos (MTP) y pulsa Permitir en la pantalla del dispositivo.",
  "fr": "Aucun appareil connecté. Réglez l'USB en mode transfert de fichiers (MTP) et appuyez sur Autoriser sur l'écran de l'appareil."
 },
 "ROM 폴더 (선택 - 넣으면 ROM 파일도 확인합니다)": {
  "en": "ROM folder (optional - if set, ROM files are checked too)",
  "ja": "ROMフォルダー(任意 - 指定するとROMファイルも確認します)",
  "es": "Carpeta ROM (opcional - si se indica, también se comprueban los archivos ROM)",
  "fr": "Dossier ROM (facultatif - s'il est défini, les fichiers ROM sont aussi vérifiés)"
 },
 "Plan을 실제 파일에 적용합니다": {
  "en": "Applies the Plan to the actual files",
  "ja": "Planを実際のファイルに適用します",
  "es": "Aplica el Plan a los archivos reales",
  "fr": "Applique le Plan aux fichiers réels"
 },
 "계산해둔 변경을 버립니다": {
  "en": "Discards the calculated changes",
  "ja": "計算済みの変更を破棄します",
  "es": "Descarta los cambios calculados",
  "fr": "Annule les modifications calculées"
 },
 "계산해둔 변경을 모두 버립니다. 실제 파일은 바뀌지 않습니다.": {
  "en": "Discards all calculated changes. The actual files are not changed.",
  "ja": "計算済みの変更をすべて破棄します。実際のファイルは変わりません。",
  "es": "Descarta todos los cambios calculados. Los archivos reales no cambian.",
  "fr": "Annule toutes les modifications calculées. Les fichiers réels ne changent pas."
 },
 "이미 있는 게임은 비어 있는 값과 없는 미디어만 원본에서 채웁니다. 대상에 있는 값과 미디어, ROM은 그대로 둡니다.": {
  "en": "For an existing game, only fills in empty values and missing media from the source. The target's existing values, media and ROM are left as they are.",
  "ja": "既にあるゲームには、元から空の値とないMediaだけを補います。対象の既存の値・Media・ROMはそのまま残します。",
  "es": "Para un juego ya existente, solo rellena los valores vacíos y el Media que falta a partir del origen. Los valores, Media y ROM existentes del destino se dejan tal cual.",
  "fr": "Pour un jeu déjà existant, ne remplit que les valeurs vides et les Media manquants depuis la source. Les valeurs, Media et ROM existants de la cible sont laissés tels quels."
 },
 "원본의 메타데이터와 미디어가 대상 것을 대신합니다. 원본이 비어 있는 값으로 대상 값을 지우지는 않습니다.": {
  "en": "The source's metadata and media replace the target's. An empty source value never blanks out an existing target value.",
  "ja": "元のメタデータとMediaが対象のものに取って代わります。元が空の値で対象の値を消すことはありません。",
  "es": "Los metadatos y el Media del origen sustituyen a los del destino. Un valor vacío del origen nunca borra un valor existente del destino.",
  "fr": "Les métadonnées et les Media de la source remplacent ceux de la cible. Une valeur vide de la source n'efface jamais une valeur existante de la cible."
 },
 "게임의 메타데이터와 미디어를 원본 것으로 다시 만듭니다(원본에 없는 메타데이터 값은 사라집니다).": {
  "en": "Rebuilds the game's metadata and media from the source (metadata values absent from the source are removed).",
  "ja": "ゲームのメタデータとMediaを元のもので作り直します(元にないメタデータの値は消えます)。",
  "es": "Reconstruye los metadatos y el Media del juego a partir del origen (los valores de metadatos ausentes en el origen se eliminan).",
  "fr": "Reconstruit les métadonnées et les Media du jeu à partir de la source (les valeurs de métadonnées absentes de la source sont supprimées)."
 },
 "대상에만 있는 미디어 파일은 지우지 않습니다. ROM은 어느 모드에서도 유지되며, 바꾸려면 설정의 'ROM도 교체'를 켜세요.": {
  "en": "Media files that exist only in the target are not deleted. The ROM is kept in every mode - to replace it, turn on 'Replace ROM too' in Settings.",
  "ja": "対象にのみあるMediaファイルは削除しません。ROMはどのモードでも保持され、変更するには設定の「ROMも置換」をオンにしてください。",
  "es": "Los archivos de Media que solo existen en el destino no se eliminan. La ROM se conserva en todos los modos - para reemplazarla, activa \"Reemplazar también la ROM\" en la configuración.",
  "fr": "Les fichiers Media qui n'existent que dans la cible ne sont pas supprimés. La ROM est conservée dans tous les modes - pour la remplacer, activez « Remplacer aussi la ROM » dans les paramètres."
 },
 "프로그램의 기본 동작": {
  "en": "The program's basic behavior",
  "ja": "プログラムの基本動作",
  "es": "Comportamiento básico del programa",
  "fr": "Comportement de base du programme"
 },
 "Collection 열기와 세션": {
  "en": "Opening Collections and sessions",
  "ja": "Collectionを開く・セッション",
  "es": "Apertura de Collections y sesiones",
  "fr": "Ouverture des Collections et sessions"
 },
 "목록과 메타데이터 표시": {
  "en": "List and metadata display",
  "ja": "一覧とメタデータの表示",
  "es": "Visualización de la lista y los metadatos",
  "fr": "Affichage de la liste et des métadonnées"
 },
 "가져오기와 내보내기": {
  "en": "Import and export",
  "ja": "インポートとエクスポート",
  "es": "Importación y exportación",
  "fr": "Importation et exportation"
 },
 "저장 형식과 위치": {
  "en": "Storage format and location",
  "ja": "保存形式と場所",
  "es": "Formato y ubicación de almacenamiento",
  "fr": "Format et emplacement de stockage"
 },
 "RetroArch 연동": {
  "en": "RetroArch integration",
  "ja": "RetroArch連携",
  "es": "Integración con RetroArch",
  "fr": "Intégration RetroArch"
 },
 "테마와 화면 밀도": {
  "en": "Theme and screen density",
  "ja": "テーマと画面密度",
  "es": "Tema y densidad de pantalla",
  "fr": "Thème et densité d'écran"
 },
 "캐시와 진단": {
  "en": "Cache and diagnostics",
  "ja": "キャッシュと診断",
  "es": "Caché y diagnóstico",
  "fr": "Cache et diagnostic"
 },
 "닫기 (Esc)": {
  "en": "Close (Esc)",
  "ja": "閉じる (Esc)",
  "es": "Cerrar (Esc)",
  "fr": "Fermer (Échap)"
 },
 "매칭되는 ROM이 없으면 Metadata/Media를 복사하지 않음": {
  "en": "If there is no matching ROM, do not copy Metadata/Media",
  "ja": "マッチするROMがなければMetadata/Mediaをコピーしない",
  "es": "Si no hay una ROM coincidente, no copiar Metadata/Media",
  "fr": "Si aucune ROM ne correspond, ne pas copier les Metadata/Media"
 },
 "매칭되는 ROM이 없어도 다음을 복사": {
  "en": "Copy the following even without a matching ROM",
  "ja": "マッチするROMがなくても次をコピー",
  "es": "Copiar lo siguiente aunque no haya una ROM coincidente",
  "fr": "Copier ce qui suit même sans ROM correspondante"
 },
 "선택한 항목의 원본에 ROM 파일이 없을 때(예: Archive 항목) 무엇을 붙여넣을지 정합니다.": {
  "en": "Decides what to paste when the selected item's source has no ROM file (e.g. an Archive item).",
  "ja": "選んだ項目の元にROMファイルがない場合(例: Archive項目)、何を貼り付けるかを決めます。",
  "es": "Decide qué pegar cuando el origen del elemento seleccionado no tiene archivo ROM (por ejemplo, un elemento de Archive).",
  "fr": "Détermine ce qui est collé lorsque la source de l'élément sélectionné n'a pas de fichier ROM (par ex. un élément d'Archive)."
 },
 "RetroMeta Studio의 전역 동작을 설정합니다.": {
  "en": "Configures RetroMeta Studio's global behavior.",
  "ja": "RetroMeta Studioの全体動作を設定します。",
  "es": "Configura el comportamiento global de RetroMeta Studio.",
  "fr": "Configure le comportement global de RetroMeta Studio."
 },
 "앱을 다시 켜면 마지막에 열어 둔 Collection 탭을 모두 되살립니다(끄면 첫 Collection만 엽니다).": {
  "en": "Restores every Collection tab that was open last time when the app starts again (if off, only the first Collection opens).",
  "ja": "アプリを再起動すると、最後に開いていたCollectionタブをすべて復元します(オフの場合は最初のCollectionのみ開きます)。",
  "es": "Al reiniciar la aplicación, restaura todas las pestañas de Collection que estaban abiertas la última vez (si está desactivado, solo se abre la primera Collection).",
  "fr": "Au redémarrage de l'application, restaure tous les onglets de Collection ouverts la dernière fois (si désactivé, seule la première Collection s'ouvre)."
 },
 "Collection마다 마지막으로 고른 System/Storage에서 시작합니다.": {
  "en": "Starts each Collection at the System/Storage it last had selected.",
  "ja": "Collectionごとに最後に選んだSystem/Storageから開始します。",
  "es": "Cada Collection empieza en el System/Storage que se seleccionó por última vez.",
  "fr": "Chaque Collection démarre sur le System/Storage sélectionné en dernier."
 },
 "좌측 SYSTEMS 목록에서 게임이 없는 System을 숨깁니다. SYSTEMS 제목 옆 눈 아이콘으로도 바꿀 수 있습니다.": {
  "en": "Hides Systems with no games from the SYSTEMS list on the left. Can also be toggled with the eye icon next to the SYSTEMS title.",
  "ja": "左側のSYSTEMS一覧でゲームがないSystemを隠します。SYSTEMSタイトル横の目のアイコンでも切り替えられます。",
  "es": "Oculta en la lista SYSTEMS de la izquierda los System sin juegos. También se puede alternar con el icono de ojo junto al título SYSTEMS.",
  "fr": "Masque dans la liste SYSTEMS à gauche les System sans jeux. Peut aussi être basculé avec l'icône d'œil à côté du titre SYSTEMS."
 },
 "Collection을 새로 열 때 목록의 기본 우선 정렬입니다. Toolbar에서 그때그때 바꿀 수 있습니다.": {
  "en": "The default priority sort for the list when a Collection is newly opened. Can be changed anytime from the Toolbar.",
  "ja": "Collectionを新しく開いたときの一覧の既定の優先ソートです。Toolbarでその都度変更できます。",
  "es": "El orden de prioridad predeterminado de la lista al abrir una Collection nueva. Se puede cambiar en cualquier momento desde la Toolbar.",
  "fr": "Le tri de priorité par défaut de la liste à l'ouverture d'une nouvelle Collection. Modifiable à tout moment depuis la Toolbar."
 },
 "ROM / Metadata / Media 경로는 Collection 탭의 우클릭 메뉴에서 관리합니다.": {
  "en": "ROM / Metadata / Media paths are managed from the Collection tab's right-click menu.",
  "ja": "ROM / Metadata / Mediaのパスは、Collectionタブの右クリックメニューで管理します。",
  "es": "Las rutas de ROM / Metadata / Media se gestionan desde el menú contextual de la pestaña de Collection.",
  "fr": "Les chemins ROM / Metadata / Media se gèrent depuis le menu contextuel de l'onglet Collection."
 },
 "Media 탭의 Screenshot 자리에서 영상을 보여줍니다. 재생 중에 누르면 멈춥니다.": {
  "en": "Shows video in the Screenshot spot of the Media tab. Clicking it while playing stops it.",
  "ja": "Mediaタブのスクリーンショット欄で動画を表示します。再生中にクリックすると止まります。",
  "es": "Muestra el vídeo en el lugar del Screenshot en la pestaña Media. Al hacer clic mientras se reproduce, se detiene.",
  "fr": "Affiche la vidéo à l'emplacement du Screenshot dans l'onglet Media. Cliquer dessus pendant la lecture l'arrête."
 },
 "게임을 고르고 이 시간만큼 그대로 두면 재생합니다. 그 전에 다른 게임으로 넘기면 재생하지 않습니다.": {
  "en": "Plays after you select a game and leave it alone for this long. Switching to another game before that cancels playback.",
  "ja": "ゲームを選んでこの時間そのままにすると再生します。その前に別のゲームに切り替えると再生しません。",
  "es": "Se reproduce después de seleccionar un juego y dejarlo así durante este tiempo. Cambiar a otro juego antes cancela la reproducción.",
  "fr": "Se lance après avoir sélectionné un jeu et l'avoir laissé ainsi pendant ce délai. Passer à un autre jeu avant annule la lecture."
 },
 "구역은 ROM 파일명의 지역 태그로 정합니다 - (KR), [Kor], _k, (USA), global 같은 표시입니다.": {
  "en": "The region is determined by the region tag in the ROM filename - markers like (KR), [Kor], _k, (USA), global.",
  "ja": "地域はROMファイル名の地域タグで決まります - (KR)、[Kor]、_k、(USA)、globalのような表記です。",
  "es": "La región se determina por la etiqueta de región del nombre del archivo ROM - marcas como (KR), [Kor], _k, (USA), global.",
  "fr": "La région est déterminée par la balise de région dans le nom du fichier ROM - des marqueurs comme (KR), [Kor], _k, (USA), global."
 },
 "해당 구역이 켜져 있으면 제목 양 끝의 기존 장식을 떼고(디스크 표시는 보존) 아래 텍스트를": {
  "en": "If that region is on, strips the existing decoration from both ends of the title (disc markers are preserved) and the text below",
  "ja": "その地域がオンなら、タイトル両端の既存の装飾を外し(ディスク表示は保持)、下のテキストを",
  "es": "Si esa región está activada, quita la decoración existente de ambos extremos del título (se conservan las marcas de disco) y el texto de abajo",
  "fr": "Si cette région est activée, retire la décoration existante des deux côtés du titre (les marqueurs de disque sont conservés) et le texte ci-dessous"
 },
 "다시 붙입니다. 태그가 없는 파일은 미분류라 건드리지 않습니다.": {
  "en": "is reapplied. Files with no tag are unclassified and left untouched.",
  "ja": "を付け直します。タグのないファイルは未分類のため触りません。",
  "es": "se vuelve a aplicar. Los archivos sin etiqueta quedan sin clasificar y no se modifican.",
  "fr": "est réappliqué. Les fichiers sans balise sont non classés et ne sont pas modifiés."
 },
 "문구 앞뒤의 공백은 그대로 쓰입니다(예: \\\" (KR)\\\"). 파일명에 지역이 여럿이면((Japan, Europe)) 켜진 구역의": {
  "en": "Spaces before and after the text are used as-is (e.g. \" (KR)\"). If a filename has several regions ((Japan, Europe)), the text of every enabled region",
  "ja": "文言の前後の空白はそのまま使われます(例: \" (KR)\")。ファイル名に地域が複数ある場合((Japan, Europe))、オンになっている地域の",
  "es": "Los espacios antes y después del texto se usan tal cual (por ejemplo, \" (KR)\"). Si un nombre de archivo tiene varias regiones ((Japan, Europe)), el texto de cada región activada",
  "fr": "Les espaces avant et après le texte sont utilisés tels quels (par ex. « (KR) »). Si un nom de fichier a plusieurs régions ((Japan, Europe)), le texte de chaque région activée"
 },
 "문구를 모두 붙이고, 같은 괄호면 [JP][EU]가 [JP,EU]로 합쳐집니다.": {
  "en": "is all appended, and if they share the same bracket style, [JP][EU] is merged into [JP,EU].",
  "ja": "はすべて付加され、同じ括弧形式なら[JP][EU]は[JP,EU]にまとめられます。",
  "es": "se añade todo, y si comparten el mismo estilo de paréntesis, [JP][EU] se combina en [JP,EU].",
  "fr": "est ajouté, et s'ils partagent le même style de crochet, [JP][EU] est fusionné en [JP,EU]."
 },
 "실행은 Gamelist나 System 우클릭 메뉴에서 합니다.": {
  "en": "Run it from the Gamelist or the System right-click menu.",
  "ja": "実行はGamelistまたはSystemの右クリックメニューから行います。",
  "es": "Ejecútalo desde el Gamelist o el menú contextual del System.",
  "fr": "Exécutez-le depuis le Gamelist ou le menu contextuel du System."
 },
 "Collection → Collection 복사 (Ctrl+C / Ctrl+V)": {
  "en": "Collection → Collection copy (Ctrl+C / Ctrl+V)",
  "ja": "Collection → Collectionコピー (Ctrl+C / Ctrl+V)",
  "es": "Copia Collection → Collection (Ctrl+C / Ctrl+V)",
  "fr": "Copie Collection → Collection (Ctrl+C / Ctrl+V)"
 },
 "Patch - 보완(없는 것만 채움)": {
  "en": "Patch - fill only what is missing",
  "ja": "Patch - 補完(足りないものだけ)",
  "es": "Patch - completar (solo lo que falta)",
  "fr": "Patch - compléter (uniquement ce qui manque)"
 },
 "Overwrite - 덮어쓰기(원본 값 적용)": {
  "en": "Overwrite - apply the source values",
  "ja": "Overwrite - 上書き(元の値を適用)",
  "es": "Overwrite - aplicar los valores de origen",
  "fr": "Overwrite - appliquer les valeurs de la source"
 },
 "Replace - 완전 교체(원본으로 다시 만듦)": {
  "en": "Replace - rebuild from the source",
  "ja": "Replace - 完全置換(元から作り直す)",
  "es": "Replace - reconstruir desde el origen",
  "fr": "Replace - reconstruire depuis la source"
 },
 "Patch: 이미 있는 항목의 빈 값과 없는 미디어만 채웁니다. Overwrite: 원본의 값과 미디어가 대상 것을 대신합니다. Replace: 게임의 메타데이터와 미디어를 원본으로 다시 만듭니다. 상단 Plan 버튼 옆에서도 바꿀 수 있습니다.": {
  "en": "Patch: fills only the empty values and missing media of an existing item. Overwrite: the source's values and media replace the target's. Replace: rebuilds the game's metadata and media from the source. You can also change this next to the Plan button at the top.",
  "ja": "Patch: 既存項目の空の値とないMediaだけを補います。Overwrite: 元の値とMediaが対象のものに代わります。Replace: ゲームのメタデータとMediaを元から作り直します。上部のPlanボタン横でも変更できます。",
  "es": "Patch: rellena solo los valores vacíos y el Media que falta de un elemento existente. Overwrite: los valores y el Media del origen sustituyen a los del destino. Replace: reconstruye los metadatos y el Media del juego desde el origen. También puedes cambiarlo junto al botón Plan de arriba.",
  "fr": "Patch : ne remplit que les valeurs vides et les Media manquants d'un élément existant. Overwrite : les valeurs et les Media de la source remplacent ceux de la cible. Replace : reconstruit les métadonnées et les Media du jeu depuis la source. Modifiable aussi à côté du bouton Plan en haut."
 },
 "기본은 꺼짐 - 대상에 ROM이 있으면 어느 모드에서도 그대로 둡니다. 켜면 원본 ROM으로 바꾸며, 그때만 같은 파일인지/다른 파일인지 확인(충돌 판정)이 ROM에 적용됩니다.": {
  "en": "Off by default - if the target has a ROM, it is left alone in every mode. When on, it is replaced with the source ROM, and only then does the same-file/different-file check (conflict detection) apply to the ROM.",
  "ja": "既定はオフ - 対象にROMがあればどのモードでもそのままにします。オンにすると元のROMに置き換え、そのときだけ同一ファイルか別ファイルかの確認(競合判定)がROMに適用されます。",
  "es": "Desactivado por defecto - si el destino tiene una ROM, se deja tal cual en cualquier modo. Al activarlo, se reemplaza por la ROM de origen, y solo entonces se aplica a la ROM la comprobación de mismo archivo/archivo distinto (detección de conflictos).",
  "fr": "Désactivé par défaut - si la cible a une ROM, elle est laissée telle quelle dans tous les modes. Activé, elle est remplacée par la ROM source, et c'est alors seulement que la vérification même fichier/fichier différent (détection de conflit) s'applique à la ROM."
 },
 "Media 복사": {
  "en": "Copy Media",
  "ja": "Mediaをコピー",
  "es": "Copiar Media",
  "fr": "Copier les Media"
 },
 "이번 붙여넣기로 생긴 충돌에만 적용합니다. 메타데이터는 어느 경우에도 붙여넣습니다.": {
  "en": "Applies only to conflicts created by this paste. Metadata is pasted in every case.",
  "ja": "今回の貼り付けで生じた競合にのみ適用します。メタデータはどの場合でも貼り付けます。",
  "es": "Se aplica solo a los conflictos creados por este pegado. Los metadatos se pegan en cualquier caso.",
  "fr": "S'applique uniquement aux conflits créés par ce collage. Les métadonnées sont collées dans tous les cas."
 },
 "Archive를 어디에 어떤 형식으로 저장할지 정합니다.": {
  "en": "Decides where and in what format the Archive is stored.",
  "ja": "Archiveをどこにどの形式で保存するか決めます。",
  "es": "Decide dónde y en qué formato se guarda el Archive.",
  "fr": "Détermine où et dans quel format l'Archive est stockée."
 },
 "Archive 설정은 준비 중입니다.": {
  "en": "Archive settings are coming soon.",
  "ja": "Archive設定は準備中です。",
  "es": "La configuración de Archive está próximamente.",
  "fr": "Les paramètres d'Archive arrivent bientôt."
 },
 "외부 에뮬레이터 실행에 필요한 설정입니다.": {
  "en": "Settings needed to launch an external emulator.",
  "ja": "外部エミュレーター起動に必要な設定です。",
  "es": "Configuración necesaria para iniciar un emulador externo.",
  "fr": "Paramètres nécessaires pour lancer un émulateur externe."
 },
 "RetroArch 설정은 준비 중입니다.": {
  "en": "RetroArch settings are coming soon.",
  "ja": "RetroArch設定は準備中です。",
  "es": "La configuración de RetroArch está próximamente.",
  "fr": "Les paramètres RetroArch arrivent bientôt."
 },
 "Stitch는 절제된 어두운 기본 팔레트입니다. SFC는 콘솔 버튼 4색, MD는 빨강+금색, NES는 베이지+빨강+금색을 씁니다.": {
  "en": "Stitch is a restrained dark default palette. SFC uses the console's four button colors, MD uses red+gold, and NES uses beige+red+gold.",
  "ja": "Stitchは抑えたダークな既定パレットです。SFCはコンソールのボタン4色、MDは赤+金、NESはベージュ+赤+金を使います。",
  "es": "Stitch es una paleta oscura predeterminada y sobria. SFC usa los cuatro colores de los botones de la consola, MD usa rojo+dorado y NES usa beige+rojo+dorado.",
  "fr": "Stitch est une palette sombre par défaut sobre. SFC utilise les quatre couleurs des boutons de la console, MD utilise rouge+or, et NES beige+rouge+or."
 },
 "처음 여는 Collection에서 미리보기를 켤지 정합니다. 이미 연 Collection은 마지막 상태를 따릅니다.": {
  "en": "Decides whether preview is on for a Collection you open for the first time. A Collection already opened keeps its last state.",
  "ja": "初めて開くCollectionでプレビューをオンにするか決めます。既に開いたCollectionは最後の状態に従います。",
  "es": "Decide si la vista previa está activada para una Collection que abres por primera vez. Una Collection ya abierta mantiene su último estado.",
  "fr": "Détermine si l'aperçu est activé pour une Collection ouverte pour la première fois. Une Collection déjà ouverte conserve son dernier état."
 },
 "영어권(EN)": {
  "en": "English (EN)",
  "ja": "英語圏 (EN)",
  "es": "Anglófono (EN)",
  "fr": "Anglophone (EN)"
 },
 "일본(JP)": {
  "en": "Japan (JP)",
  "ja": "日本 (JP)",
  "es": "Japón (JP)",
  "fr": "Japon (JP)"
 },
 "유럽(EU)": {
  "en": "Europe (EU)",
  "ja": "欧州 (EU)",
  "es": "Europa (EU)",
  "fr": "Europe (EU)"
 },
 "글로벌": {
  "en": "Global",
  "ja": "グローバル",
  "es": "Global",
  "fr": "Mondial"
 },
 "예: KR": {
  "en": "e.g. KR",
  "ja": "例: KR",
  "es": "p. ej. KR",
  "fr": "ex. KR"
 }
});

  // 값 하나가 문장 가운데(끝이 아니라)에 끼는 동적 문구 - i18n.js의 PATTERNS는 값이
  // 문장 앞/뒤에만 있는 모양을 전제해서 이런 것들은 표(addTable)에 넣을 수 없다
  // (원문 자체가 실행마다 달라져 정확히 일치하는 키가 없다). $1/$2로 캡처한 값은
  // 번역하지 않고 그대로 옮긴다 - 이름/개수 같은 사용자 데이터이기 때문이다.
  const P = i18n.P;
  i18n.addPatterns([
    P(String.raw`^비워 두면 "(.+)"\(으\)로 만듭니다\.$`,
      'Leave empty to create it as "$1".', '空欄の場合は「$1」として作成します。',
      'Déjalo vacío para crearlo como "$1".', 'Laissez vide pour le créer comme « $1 ».'),
    P(String.raw`^External ROM 디렉토리는 추가하지 못했습니다: (.+)$`,
      'Could not add the External ROM directory: $1', '外部ROMディレクトリを追加できませんでした: $1',
      'No se pudo añadir el directorio ROM externo: $1', "Impossible d'ajouter le répertoire ROM externe : $1"),
    P(String.raw`^동시에 열 수 있는 Collection은 (\d[\d,]*)개까지입니다\.$`,
      'Up to $1 Collections can be open at the same time.', '同時に開けるCollectionは$1個までです。',
      'Se pueden abrir hasta $1 Collections al mismo tiempo.', "Vous pouvez ouvrir jusqu'à $1 Collections en même temps."),
    P(String.raw`^게임 (\d[\d,]*) · (.+)$`,
      'Games $1 · $2', 'ゲーム $1 · $2', 'Juegos $1 · $2', 'Jeux $1 · $2'),
    P(String.raw`^빈 System 보이기 \(숨김 (\d[\d,]*)개\)$`,
      'Show empty Systems (hidden: $1)', '空のSystemを表示(非表示 $1件)',
      'Mostrar Systems vacíos (ocultos: $1)', 'Afficher les Systems vides (masqués : $1)'),
    P(String.raw`^Archive에 (\d[\d,]*)개를 (\d[\d,]*)개 System으로 정리했습니다\.$`,
      'Organized $1 items in the Archive into $2 Systems.', 'Archiveの$1件を$2個のSystemに整理しました。',
      'Se organizaron $1 elementos del Archive en $2 Systems.',
      "$1 éléments de l'Archive ont été organisés en $2 Systems."),
    P(String.raw`^\(이전 Archive (\d[\d,]*)개 가져옴\)$`,
      '(imported $1 from the previous Archive)', '(以前のArchiveから$1件をインポート)',
      '(se importaron $1 del Archive anterior)', "($1 importés depuis l'Archive précédente)"),
    P(String.raw`^"(.+)"을 제거합니다\. 이 안의 System (\d[\d,]*)개\((.+)\)를 Internal로 합칩니다\. 실제 파일은 지금 있는 자리에 그대로 남고, 목록에서의 표시만 바뀝니다\.$`,
      'Removing "$1". The $2 System(s) inside it ($3) will be merged into Internal. The actual files stay where they are - only the listing changes.',
      '「$1」を削除します。この中のSystem $2個($3)はInternalに統合されます。実際のファイルは今の場所にそのまま残り、一覧上の表示のみ変わります。',
      'Se va a quitar "$1". Los $2 System dentro ($3) se fusionarán en Internal. Los archivos reales se quedan donde están - solo cambia el listado.',
      'Suppression de « $1 ». Le(s) $2 System à l\'intérieur ($3) seront fusionnés dans Internal. Les fichiers réels restent où ils sont - seul l\'affichage change.'),
    P(String.raw`^"(.+)"을 제거합니다\. 이 안에는 System이 없습니다\.$`,
      'Removing "$1". There are no Systems inside it.', '「$1」を削除します。この中にSystemはありません。',
      'Se va a quitar "$1". No hay ningún System dentro.', 'Suppression de « $1 ». Il n\'y a aucun System à l\'intérieur.'),
    P(String.raw`^"(.+)"을 제거했습니다\.$`,
      'Removed "$1".', '「$1」を削除しました。', 'Se quitó "$1".', '« $1 » a été supprimé.'),
    P(String.raw`^(.+) 폴더 이름 바꾸기…$`,
      'Rename the $1 folder…', '$1フォルダーの名前を変更…', 'Cambiar el nombre de la carpeta $1…',
      'Renommer le dossier $1…'),
    P(String.raw`^(.+) 폴더 삭제…$`,
      'Delete the $1 folder…', '$1フォルダーを削除…', 'Eliminar la carpeta $1…', 'Supprimer le dossier $1…'),
    P(String.raw`^같은 System 폴더가 여러 Storage에 있어 쓰기가 막혔습니다\.\n([\s\S]*)\n우클릭에서 한쪽 폴더를 지우거나 이름을 바꾸세요\.$`,
      'Writing is blocked because the same System folder exists in more than one Storage.\n$1\nRight-click to delete or rename one of the folders.',
      '同じSystemフォルダーが複数のStorageにあるため書き込みがブロックされています。\n$1\n右クリックでどちらかのフォルダーを削除するか名前を変更してください。',
      'La escritura está bloqueada porque la misma carpeta de System existe en más de un Storage.\n$1\nHaz clic derecho para eliminar o renombrar una de las carpetas.',
      'L\'écriture est bloquée car le même dossier System existe dans plusieurs Storage.\n$1\nFaites un clic droit pour supprimer ou renommer l\'un des dossiers.'),
    P(String.raw`^(.+) · (\d[\d,]*)개\n이동 예정: (.+) → (.+)\(Apply로 확정\)$`,
      '$1 · $2\nMove pending: $3 → $4 (confirm with Apply)',
      '$1 · $2件\n移動予定: $3 → $4(Applyで確定)',
      '$1 · $2\nMovimiento pendiente: $3 → $4 (confirmar con Apply)',
      '$1 · $2\nDéplacement en attente : $3 → $4 (confirmer avec Apply)'),
    P(String.raw`^(.+) · (\d[\d,]*)개 · (.+)\n(.+)$`,
      '$1 · $2 · $3\n$4', '$1 · $2件 · $3\n$4', '$1 · $2 · $3\n$4', '$1 · $2 · $3\n$4'),
  ]);
})();
