// Convenience barrel for module UIs: import { api, h, t, dataTable, ... } from "../core/index.js";
export { api, ApiError, upload, apiUrl, cachedAt, uuid } from "./api.js";
export { h, html, mount, append, clear, qs, qsa, on, debounce, withBusy, escapeHtml, safeHref, safeColor, initials, loadStylesheet } from "./dom.js";
export {
  t, getLang, isRtl, localName, formatDate, formatTime, formatDateTime, formatRelative, formatNumber, formatMoney,
  formatBytes, toDateInput, toDateTimeInput, todayISO, ageFrom, tzParts, getCurrency, TIMEZONE,
} from "./i18n.js";
export { navigate, href, deptHref, areaHref, currentRoute, refresh } from "./router.js";
export {
  getState, getUser, getPrincipal, getPortal, getCenter, getDepartments, getDepartment, getClinics, getClinic, clinicsOf,
  getActiveDepartment, subscribe,
} from "./state.js";
export { can, canAny, canAll, allowed, isSuperadmin, isSupportMode, isCenterWide, role, canClinic, managesDepartment, seesDepartment } from "./perm.js";
export { onEvent, emit } from "./events.js";
export { icon } from "../components/icons.js";
export { toast, toastSuccess, toastError, toastApiError, undoToast, deleteWithUndo } from "../components/toast.js";
export { openModal, openDrawer, confirmDialog, popover } from "../components/modal.js";
export { dataTable } from "../components/table.js";
export { createForm, field, readValues, setFieldErrors, clearFieldErrors, handleFormError } from "../components/form.js";
export { loadingState, emptyState, errorState, unavailableState, comingSoon, offlineCopyBanner, statusPill } from "../components/states.js";
export { tabs } from "../components/tabs.js";
export { patientSearch, patientName } from "../components/patient-search.js";
export { createUploader, MAX_FILE_BYTES } from "../components/uploader.js";
export { openImageViewer, openFileViewer } from "../components/image-viewer.js";
export { printPdf, printView, printElement, printButton } from "../components/print.js";
export { listenBarcode } from "../components/barcode.js";
