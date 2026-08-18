// osgb_full.cpp — OSGB PagedLOD 分层回退导出
// 正确语义: 每区域取"最深可用 LOD"
//   - PagedLOD 有更深子文件且未超目标LOD → 递归用子文件(丢弃本层内置几何)
//   - 无更深子文件 → 保留本层内置几何(该区域的最深可用层)
// 效果: L22 有数据的区域用 L22, 没有的区域自动回退 L21, 无空洞!
// 用法: osgb_full <root.osgb> <output.obj> <max_lod>
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <osg/Node>
#include <osg/Group>
#include <osg/Geode>
#include <osg/Geometry>
#include <osg/PagedLOD>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <osgDB/FileUtils>
#include <osgDB/FileNameUtils>
#include <osgDB/Registry>
#include <osg/StateSet>
#include <osg/Texture2D>
#include <osg/Image>
#include <osgUtil/Optimizer>
#include <iostream>
#include <string>
#include <set>
#include <map>
#include <cstdlib>

static int lod_level(const std::string& fn)
{
    size_t p = fn.find("_L");
    if (p == std::string::npos) return 0;
    p += 2;
    size_t q = fn.find('_', p);
    if (q == std::string::npos) return 0;
    return std::atoi(fn.substr(p, q - p).c_str());
}

// 递归收集: 每区域取最深可用 LOD
static void collect_lod(osg::Node* node, osg::Group* out, int max_lod,
                        std::set<std::string>& loaded, const std::string& base_dir)
{
    osg::PagedLOD* plod = dynamic_cast<osg::PagedLOD*>(node);
    if (plod) {
        bool has_loaded_child = false;
        // 尝试加载更深子瓦片
        for (unsigned i = 0; i < plod->getNumFileNames(); ++i) {
            const std::string& fn = plod->getFileName(i);
            if (fn.empty() || fn.find(".osgb") == std::string::npos) continue;
            int lvl = lod_level(fn);
            if (max_lod > 0 && lvl > max_lod) continue;  // 超目标LOD: 用当前层
            if (loaded.count(fn)) continue;
            loaded.insert(fn);
            std::string full = base_dir.empty() ? fn : base_dir + "\\" + fn;
            osg::ref_ptr<osg::Node> child = osgDB::readNodeFile(full);
            if (child.valid()) {
                collect_lod(child.get(), out, max_lod, loaded, base_dir);
                has_loaded_child = true;
            } else {
                std::cerr << "  [warn] 加载失败: " << full << std::endl;
            }
        }
        // 有更深子瓦片 → 本层内置几何被替代, 丢弃
        // 无更深子瓦片 → 本层是该区域最深可用, 保留内置几何
        if (!has_loaded_child) {
            for (unsigned i = 0; i < plod->getNumChildren(); ++i) {
                collect_lod(plod->getChild(i), out, max_lod, loaded, base_dir);
            }
        }
    } else if (osg::Geode* geode = node->asGeode()) {
        out->addChild(geode);
    } else if (osg::Group* grp = node->asGroup()) {
        for (unsigned i = 0; i < grp->getNumChildren(); ++i)
            collect_lod(grp->getChild(i), out, max_lod, loaded, base_dir);
    }
}

static void count_geoms(osg::Node* node, unsigned& verts, unsigned& faces)
{
    osg::Geode* geode = node->asGeode();
    if (geode) {
        for (unsigned i = 0; i < geode->getNumDrawables(); ++i) {
            osg::Geometry* g = geode->getDrawable(i)->asGeometry();
            if (g) {
                verts += (g->getVertexArray() ? g->getVertexArray()->getNumElements() : 0);
                for (auto& p : g->getPrimitiveSetList()) {
                    GLenum m = p->getMode();
                    if (m == GL_TRIANGLES) faces += p->getNumIndices() / 3;
                    else if (m == GL_TRIANGLE_STRIP || m == GL_TRIANGLE_FAN) faces += p->getNumIndices() - 2;
                    else if (m == GL_QUADS) faces += p->getNumIndices() / 2;
                }
            }
        }
    }
    osg::Group* grp = node->asGroup();
    if (grp) for (unsigned i = 0; i < grp->getNumChildren(); ++i)
        count_geoms(grp->getChild(i), verts, faces);
}

int main(int argc, char* argv[])
{
    if (argc < 4) {
        std::cerr << "Usage: osgb_full <root.osgb> <output.obj> <max_lod>\n"
                  << "  每区域取最深可用 LOD(如 max_lod=22 时 L22 缺失处自动用 L21)\n";
        return 1;
    }
    std::string input = argv[1];
    std::string output = argv[2];
    int max_lod = std::atoi(argv[3]);

    std::string dir = input.substr(0, input.find_last_of("\\/"));
    osgDB::Registry::instance()->getDataFilePathList().push_back(dir);

    osg::ref_ptr<osg::Node> root = osgDB::readNodeFile(input);
    if (!root.valid()) {
        std::cerr << "Failed to read: " << input << std::endl;
        return 2;
    }

    osg::ref_ptr<osg::Group> merged = new osg::Group;
    std::set<std::string> loaded;
    collect_lod(root.get(), merged.get(), max_lod, loaded, dir);
    std::cout << "Collected with max_lod=" << max_lod << std::endl;

    osgUtil::Optimizer opt;
    opt.optimize(merged.get(), osgUtil::Optimizer::FLATTEN_STATIC_TRANSFORMS |
                               osgUtil::Optimizer::REMOVE_REDUNDANT_NODES |
                               osgUtil::Optimizer::MERGE_GEOMETRY);

    unsigned verts = 0, faces = 0;
    count_geoms(merged.get(), verts, faces);
    std::cout << "Total: " << verts << " vertices, " << faces << " faces" << std::endl;

    // 给所有 Image 设文件名, 让 OBJ 写入器生成 usemtl/MTL 纹理引用
    struct TexCollect : public osg::NodeVisitor {
        std::map<osg::Image*, std::string> names;
        int counter = 0;
        TexCollect() : osg::NodeVisitor(osg::NodeVisitor::TRAVERSE_ALL_CHILDREN) {}
        void apply(osg::Node& node) override {
            collect(node.getStateSet());
            traverse(node);
        }
        void apply(osg::Geode& geode) override {
            collect(geode.getStateSet());
            for (unsigned i = 0; i < geode.getNumDrawables(); ++i)
                collect(geode.getDrawable(i)->getStateSet());
            traverse(geode);
        }
        void collect(osg::StateSet* ss) {
            if (!ss) return;
            for (unsigned i = 0; i < ss->getTextureAttributeList().size(); ++i) {
                osg::Texture2D* t2d = dynamic_cast<osg::Texture2D*>(ss->getTextureAttribute(i, osg::StateAttribute::TEXTURE));
                if (!t2d) continue;
                osg::Image* img = t2d->getImage();
                if (img && names.find(img) == names.end()) {
                    char buf[64];
                    snprintf(buf, sizeof(buf), "texture_%03d.jpg", counter++);
                    img->setFileName(buf);
                    names[img] = buf;
                }
            }
        }
    };
    TexCollect texCollect;
    merged->accept(texCollect);
    std::cout << "Textures: " << texCollect.names.size() << std::endl;

    if (!osgDB::writeNodeFile(*merged, output)) {
        std::cerr << "Failed to write: " << output << std::endl;
        return 3;
    }
    std::cout << "Written: " << output << std::endl;

    // 写纹理文件到输出目录(OBJ 同目录)
    std::string outDir = osgDB::getFilePath(output);
    if (outDir.empty()) outDir = ".";
    for (auto& kv : texCollect.names) {
        std::string path = outDir + "\\" + kv.second;
        if (osgDB::writeImageFile(*kv.first, path))
            std::cout << "  tex " << kv.second << " (" << kv.first->s() << "x" << kv.first->t() << ")" << std::endl;
        else
            std::cerr << "  FAILED " << kv.second << std::endl;
    }
    return 0;
}
